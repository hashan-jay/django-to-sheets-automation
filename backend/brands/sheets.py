"""Append completed deposits and withdrawals to the Google Sheet entered in the UI.

Same credential style as finance-automation: a service-account JSON file and gspread.
The spreadsheet must be shared with the service account as Editor.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from brands.models import GoogleSheetSetting, SheetExport, Transaction

log = logging.getLogger("django")

_SHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID_RE = re.compile(r"[?#&]gid=(\d+)")
_lock = threading.Lock()

CREDENTIALS = Path(settings.BASE_DIR).parent / "secrets" / "google-sheets.json"
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1AsiDeo0e08NEehnnsJZGd29dVXLIMlQ-KaUF_-mW-zY/edit?gid=2040112683"
)
DEPOSIT_START = 105
WITHDRAW_START = 1024
DEPOSIT_END = WITHDRAW_START - 1


def normalize_google_sheet_id(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    match = _SHEET_URL_RE.search(text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", text):
        return text
    return ""


def worksheet_gid(raw: object) -> int | None:
    match = _GID_RE.search(str(raw or ""))
    return int(match.group(1)) if match else None


def google_sheet_url(sheet_id: object) -> str:
    key = normalize_google_sheet_id(sheet_id)
    return f"https://docs.google.com/spreadsheets/d/{key}" if key else ""


def sheet_setting() -> GoogleSheetSetting:
    row, _created = GoogleSheetSetting.objects.get_or_create(
        pk=1,
        defaults={"sheet_url": DEFAULT_SHEET_URL},
    )
    return row


def save_sheet_url(raw: str) -> GoogleSheetSetting:
    text = str(raw or "").strip()
    sheet_id = normalize_google_sheet_id(text)
    if text and not sheet_id:
        raise ValueError("Paste a Google Sheets link, or clear the field to stop writing.")
    row = sheet_setting()
    row.sheet_url = text
    row.last_error = ""
    row.save(update_fields=["sheet_url", "last_error", "updated_at"])
    return row


def public_status() -> dict:
    row = sheet_setting()
    return {
        "sheet_url": row.sheet_url,
        "sheet_id": normalize_google_sheet_id(row.sheet_url),
        "last_error": row.last_error,
        "last_written_at": row.last_written_at.isoformat() if row.last_written_at else "",
        "written_count": SheetExport.objects.count(),
    }


def export_pending(limit: int = 40) -> int:
    """Append rows that have not been written yet. Safe to call from the poller."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        return _export_pending(limit)
    finally:
        _lock.release()


def _export_pending(limit: int) -> int:
    row = sheet_setting()
    sheet_id = normalize_google_sheet_id(row.sheet_url)
    if not sheet_id:
        return 0
    pending = list(
        Transaction.objects.filter(status="COMPLETED", type__in=["DEPOSIT", "WITHDRAW"])
        .exclude(sheet_export__isnull=False)
        .select_related("brand")
        .order_by("created_at", "id")[:limit]
    )
    if not pending:
        return 0
    try:
        spreadsheet = _open_spreadsheet(sheet_id)
        written = _write_cashbook(spreadsheet, pending)
    except Exception as exc:
        message = str(exc).splitlines()[0][:500]
        log.warning("Google Sheet write failed: %s", message)
        GoogleSheetSetting.objects.filter(pk=row.pk).update(last_error=message)
        return 0
    if not written:
        return 0
    GoogleSheetSetting.objects.filter(pk=row.pk).update(last_error="", last_written_at=timezone.now())
    return len(written)


def _open_spreadsheet(sheet_id: str):
    if not CREDENTIALS.is_file():
        raise FileNotFoundError(f"Service account key is missing: {CREDENTIALS}")
    import gspread

    client = gspread.service_account(filename=str(CREDENTIALS))
    return client.open_by_key(sheet_id)


def _write_cashbook(spreadsheet, pending: list[Transaction]) -> list[Transaction]:
    """Finance cashbook: date tab, deposits from row 105, withdrawals from row 1024.

    Column A is the locked day number. Writes start at column C (Bank) through L.
    """
    tabs = {str(worksheet.title).strip(): worksheet for worksheet in spreadsheet.worksheets()}
    grouped: dict[str, list[Transaction]] = {}
    for item in pending:
        grouped.setdefault(_tab_name(item), []).append(item)
    written: list[Transaction] = []
    for title, items in grouped.items():
        worksheet = tabs.get(title)
        if worksheet is None:
            raise LookupError(f"This spreadsheet has no tab named {title}.")
        ids = worksheet.col_values(7)
        deposits = [item for item in items if item.type != "WITHDRAW"]
        withdraws = [item for item in items if item.type == "WITHDRAW"]
        written.extend(_write_block(worksheet, ids, deposits, DEPOSIT_START, DEPOSIT_END, False))
        written.extend(_write_block(worksheet, ids, withdraws, WITHDRAW_START, worksheet.row_count, True))
    if written:
        SheetExport.objects.bulk_create([SheetExport(transaction=item) for item in written])
    return written


def _write_block(worksheet, id_column: list[str], items: list[Transaction], start: int, end: int, withdraw: bool):
    if not items:
        return []
    slot = _next_empty(id_column, start, end)
    if slot is None:
        kind = "withdrawal" if withdraw else "deposit"
        raise LookupError(f"No empty {kind} rows left on tab {worksheet.title}.")
    batch = items[: end - slot + 1]
    values = [_cashbook_cells(item) for item in batch]
    last = slot + len(batch) - 1
    worksheet.update(range_name=f"B{slot}:J{last}", values=values, value_input_option="USER_ENTERED")
    return batch


def _next_empty(id_column: list[str], start: int, end: int) -> int | None:
    for number in range(start, end + 1):
        current = id_column[number - 1] if number - 1 < len(id_column) else ""
        if not str(current).strip():
            return number
    return None


def _sydney(item: Transaction):
    from brands.models import SYDNEY
    from django.utils import timezone as dj_tz

    moment = item.created_at or item.processed_at
    if moment is None:
        return None
    return moment.astimezone(SYDNEY) if dj_tz.is_aware(moment) else moment.replace(tzinfo=SYDNEY)


def _tab_name(item: Transaction) -> str:
    aware = _sydney(item)
    if aware is None:
        from brands.models import sydney_today

        return str(sydney_today().day)
    return str(aware.day)


def _when(item: Transaction) -> str:
    aware = _sydney(item)
    return aware.strftime("%d/%m/%Y %H:%M") if aware else ""


def _cashbook_cells(item: Transaction) -> list[str]:
    """B Date through L Staff. Day stays in the locked column A."""
    amount = f"{item.amount:.2f}"
    if item.type == "WITHDRAW":
        amount = f"-{amount}"
        bank = ""
        status = "Withdraw"
    else:
        bank = item.bank_name or item.bank
        status = "Deposit"
    return [
        _when(item),
        bank,
        item.bank_account_name or item.acc_name or item.player_name,
        amount,
        status,
        item.external_id,
        item.brand.name,
        "",
        item.username,
    ]


def clear_exports_for_tests() -> None:
    with db_transaction.atomic():
        SheetExport.objects.all().delete()
