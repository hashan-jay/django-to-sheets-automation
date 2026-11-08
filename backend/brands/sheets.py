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
    gid = worksheet_gid(text)
    clean = google_sheet_url(sheet_id)
    if clean and gid is not None:
        clean = f"{clean}/edit?gid={gid}"
    row = sheet_setting()
    row.sheet_url = clean
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
        .order_by("txn_date", "created_at", "id")[:limit]
    )
    if not pending:
        return 0
    try:
        spreadsheet = _open_spreadsheet(sheet_id)
        written, errors = _write_cashbook(spreadsheet, pending)
    except Exception as exc:
        message = str(exc).splitlines()[0][:500]
        log.warning("Google Sheet write failed: %s", message)
        GoogleSheetSetting.objects.filter(pk=row.pk).update(last_error=message)
        return 0
    GoogleSheetSetting.objects.filter(pk=row.pk).update(
        last_error=" ".join(errors)[:500],
        last_written_at=timezone.now() if written else row.last_written_at,
    )
    return len(written)


def _open_spreadsheet(sheet_id: str):
    if not CREDENTIALS.is_file():
        raise FileNotFoundError(f"Service account key is missing: {CREDENTIALS}")
    import gspread

    client = gspread.service_account(filename=str(CREDENTIALS))
    return client.open_by_key(sheet_id)


def _write_cashbook(spreadsheet, pending: list[Transaction]) -> tuple[list[Transaction], list[str]]:
    """Finance cashbook: tab name is the transaction date's day number.

    9 November is tab "9". Deposits fill empty rows from 105. Withdrawals fill
    empty rows from 1024. Column A and any row that already has an ID are not touched.
    """
    tabs = {str(worksheet.title).strip(): worksheet for worksheet in spreadsheet.worksheets()}
    grouped: dict[str, list[Transaction]] = {}
    for item in pending:
        grouped.setdefault(_tab_name(item), []).append(item)
    written: list[Transaction] = []
    errors: list[str] = []
    for title, items in grouped.items():
        worksheet = tabs.get(title)
        if worksheet is None:
            errors.append(f"No tab named {title}.")
            continue
        try:
            ids = worksheet.col_values(7)
            existing = {str(value).strip() for value in ids if str(value).strip()}
            already = [item for item in items if item.external_id in existing]
            fresh = [item for item in items if item.external_id not in existing]
            _remember(already)
            deposits = [item for item in fresh if item.type != "WITHDRAW"]
            withdraws = [item for item in fresh if item.type == "WITHDRAW"]
            placed = _write_block(worksheet, ids, deposits, DEPOSIT_START, DEPOSIT_END)
            placed += _write_block(worksheet, ids, withdraws, WITHDRAW_START, worksheet.row_count)
            _remember(placed)
            written.extend(already)
            written.extend(placed)
            left = len(fresh) - len(placed)
            if left:
                errors.append(f"Tab {title} ran out of empty rows for {left} transaction(s).")
        except Exception as exc:
            errors.append(f"Tab {title}: {str(exc).splitlines()[0][:180]}")
            log.warning("Google Sheet tab %s failed: %s", title, exc)
    return written, errors


def _remember(items: list[Transaction]) -> None:
    if items:
        SheetExport.objects.bulk_create(
            [SheetExport(transaction=item) for item in items],
            ignore_conflicts=True,
        )


def _write_block(worksheet, id_column: list[str], items: list[Transaction], start: int, end: int):
    if not items:
        return []
    slots = _empty_slots(id_column, start, end, len(items))
    if not slots:
        return []
    batch = items[: len(slots)]
    ranges = []
    run_start = slots[0]
    run_values = [_cashbook_cells(batch[0])]
    for index in range(1, len(slots)):
        if slots[index] == slots[index - 1] + 1:
            run_values.append(_cashbook_cells(batch[index]))
            continue
        ranges.append((run_start, run_values))
        run_start = slots[index]
        run_values = [_cashbook_cells(batch[index])]
    ranges.append((run_start, run_values))
    worksheet.batch_update(
        [
            {"range": f"B{start_row}:J{start_row + len(values) - 1}", "values": values}
            for start_row, values in ranges
        ],
        value_input_option="USER_ENTERED",
    )
    for slot, item in zip(slots, batch):
        while len(id_column) < slot:
            id_column.append("")
        id_column[slot - 1] = item.external_id
    return batch


def _empty_slots(id_column: list[str], start: int, end: int, count: int) -> list[int]:
    slots: list[int] = []
    for number in range(start, end + 1):
        current = id_column[number - 1] if number - 1 < len(id_column) else ""
        if not str(current).strip():
            slots.append(number)
            if len(slots) == count:
                break
    return slots


def _tab_name(item: Transaction) -> str:
    """Day-of-month tab. 9 November 2026 is the sheet titled 9."""
    if item.txn_date is not None:
        return str(item.txn_date.day)
    from brands.models import sydney_today

    return str(sydney_today().day)


def _when(item: Transaction) -> str:
    from brands.models import SYDNEY
    from django.utils import timezone as dj_tz

    moment = item.created_at or item.processed_at
    if moment is None:
        return item.txn_date.strftime("%d/%m/%Y") if item.txn_date else ""
    aware = moment.astimezone(SYDNEY) if dj_tz.is_aware(moment) else moment.replace(tzinfo=SYDNEY)
    return aware.strftime("%d/%m/%Y %H:%M")


def _sheet_bank(item: Transaction) -> str:
    """Google Sheet Bank is the web app bank name and bank account name together."""
    bank = (item.bank_name or "").strip()
    account = (item.bank_account_name or "").strip()
    return " ".join(part for part in (bank, account) if part)


def _cashbook_cells(item: Transaction) -> list[str]:
    """B Date through J Player. Column A, Rate, and Staff are never written."""
    amount = f"{item.amount:.2f}"
    status = "Withdraw" if item.type == "WITHDRAW" else "Deposit"
    if item.type == "WITHDRAW":
        amount = f"-{amount}"
    return [
        _when(item),
        _sheet_bank(item),
        (item.player_name or "").strip(),
        amount,
        status,
        item.external_id,
        item.brand.name,
        "",
        item.username,
    ]


def repair_written_columns() -> int:
    """Correct Bank and Description on rows this app already wrote. Staff is not touched."""
    row = sheet_setting()
    sheet_id = normalize_google_sheet_id(row.sheet_url)
    if not sheet_id:
        return 0
    exported = list(
        SheetExport.objects.select_related("transaction", "transaction__brand").order_by("transaction__txn_date", "id")
    )
    if not exported:
        return 0
    spreadsheet = _open_spreadsheet(sheet_id)
    tabs = {str(worksheet.title).strip(): worksheet for worksheet in spreadsheet.worksheets()}
    grouped: dict[str, list[Transaction]] = {}
    for mark in exported:
        grouped.setdefault(_tab_name(mark.transaction), []).append(mark.transaction)
    updated = 0
    for title, items in grouped.items():
        worksheet = tabs.get(title)
        if worksheet is None:
            continue
        ids = worksheet.col_values(7)
        positions = {}
        for index, value in enumerate(ids, start=1):
            key = str(value).strip()
            if key and key not in positions:
                positions[key] = index
        ranges = []
        for item in items:
            slot = positions.get(item.external_id)
            if slot is None:
                continue
            ranges.append({"range": f"C{slot}:D{slot}", "values": [[_sheet_bank(item), (item.player_name or "").strip()]]})
        for offset in range(0, len(ranges), 200):
            chunk = ranges[offset : offset + 200]
            if chunk:
                worksheet.batch_update(chunk, value_input_option="USER_ENTERED")
                updated += len(chunk)
    return updated


def clear_exports_for_tests() -> None:
    with db_transaction.atomic():
        SheetExport.objects.all().delete()
