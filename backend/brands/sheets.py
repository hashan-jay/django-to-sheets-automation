"""Append completed deposits and withdrawals to the Google Sheet entered in the UI.

Same credential style as finance-automation: a service-account JSON file and gspread.
The spreadsheet must be shared with the service account as Editor.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.db import transaction as db_transaction
from django.utils import timezone

from brands.models import GoogleSheetSetting, SheetExport, Transaction, sydney_today

log = logging.getLogger("django")

_SHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID_RE = re.compile(r"[?#&]gid=(\d+)")
_lock = threading.Lock()
_wake = threading.Event()
_gateway_patch = threading.Event()
_writer_started = False
_writer_guard = threading.Lock()

CREDENTIALS = Path(settings.BASE_DIR).parent / "secrets" / "google-sheets.json"
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1AsiDeo0e08NEehnnsJZGd29dVXLIMlQ-KaUF_-mW-zY/edit?gid=2040112683"
)
DEFAULT_DEPOSIT_START = 105
DEFAULT_WITHDRAW_START = 1000
MIN_SHEET_START_ROW = 2
MAX_SHEET_START_ROW = 1_000_000


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


SHEET_SLOTS = (1, 2, 3)


def sheet_label(slot: int) -> str:
    return f"Google Sheet {slot}"


def _slot_number(raw) -> int:
    try:
        slot = int(raw)
    except (TypeError, ValueError):
        slot = 0
    if slot not in SHEET_SLOTS:
        raise ValueError("Choose Google Sheet 1, Google Sheet 2, or Google Sheet 3.")
    return slot


def ensure_sheet_slots() -> None:
    sheet_setting(1)
    for slot in (2, 3):
        GoogleSheetSetting.objects.get_or_create(slot=slot, defaults={"sheet_url": "", "blocked": False})


def sheet_setting(slot: int = 1) -> GoogleSheetSetting:
    slot = _slot_number(slot)
    defaults = {"sheet_url": DEFAULT_SHEET_URL if slot == 1 else "", "blocked": False}
    row, _created = GoogleSheetSetting.objects.get_or_create(slot=slot, defaults=defaults)
    return row


def active_sheet_settings() -> list[GoogleSheetSetting]:
    """Sheets that should receive live writes: a saved link, and not blocked."""
    ensure_sheet_slots()
    rows = []
    for row in GoogleSheetSetting.objects.filter(slot__in=SHEET_SLOTS).order_by("slot"):
        if row.blocked or not row.auto_sync or not normalize_google_sheet_id(row.sheet_url):
            continue
        rows.append(row)
    return rows


def save_sheet_url(raw: str, slot_raw=1) -> GoogleSheetSetting:
    slot = _slot_number(slot_raw)
    text = str(raw or "").strip()
    sheet_id = normalize_google_sheet_id(text)
    if text and not sheet_id:
        raise ValueError("Paste a Google Sheets link, or clear the field to stop writing.")
    row = sheet_setting(slot)
    if row.blocked:
        raise ValueError(f"Unblock {sheet_label(slot)} before changing its link.")
    gid = worksheet_gid(text)
    clean = google_sheet_url(sheet_id)
    if clean and gid is not None:
        clean = f"{clean}/edit?gid={gid}"
    row.sheet_url = clean
    row.sheet_name = _spreadsheet_title(sheet_id) if sheet_id else ""
    row.last_error = ""
    row.save(update_fields=["sheet_url", "sheet_name", "last_error", "updated_at"])
    return row


def set_sheet_blocked(slot_raw, blocked_raw) -> GoogleSheetSetting:
    slot = _slot_number(slot_raw)
    blocked = blocked_raw is True or str(blocked_raw).strip().lower() in {"1", "true", "yes", "on"}
    row = sheet_setting(slot)
    if blocked and not normalize_google_sheet_id(row.sheet_url):
        raise ValueError(f"Save a link for {sheet_label(slot)} before blocking it.")
    row.blocked = blocked
    row.last_error = ""
    row.save(update_fields=["blocked", "last_error", "updated_at"])
    if not blocked:
        request_export()
    return row


def set_sheet_auto_sync(slot_raw, enabled_raw) -> GoogleSheetSetting:
    slot = _slot_number(slot_raw)
    enabled = enabled_raw is True or str(enabled_raw).strip().lower() in {"1", "true", "yes", "on"}
    row = sheet_setting(slot)
    if enabled and not normalize_google_sheet_id(row.sheet_url):
        raise ValueError(f"Save a link for {sheet_label(slot)} before turning Auto Sync on.")
    row.auto_sync = enabled
    row.last_error = ""
    row.save(update_fields=["auto_sync", "last_error", "updated_at"])
    if enabled and not row.blocked:
        request_export()
    return row


def save_start_rows(deposit_raw, withdraw_raw, slot_raw=1) -> GoogleSheetSetting:
    """Same bounds as finance-automation: deposits must start before withdrawals."""
    try:
        deposit = int(str(deposit_raw).strip())
        withdraw = int(str(withdraw_raw).strip())
    except (TypeError, ValueError):
        raise ValueError("Enter a whole number for the deposit and withdraw start rows.")
    if deposit < MIN_SHEET_START_ROW or deposit > MAX_SHEET_START_ROW:
        raise ValueError("Enter a deposit start row between 2 and 1000000.")
    if withdraw < MIN_SHEET_START_ROW or withdraw > MAX_SHEET_START_ROW:
        raise ValueError("Enter a withdraw start row between 2 and 1000000.")
    if deposit >= withdraw:
        raise ValueError(
            f"Deposits must start before withdrawals. Deposit row is {deposit} and withdraw row is {withdraw}."
        )
    row = sheet_setting(_slot_number(slot_raw))
    row.deposit_start_row = deposit
    row.withdraw_start_row = withdraw
    row.last_error = ""
    row.save(update_fields=["deposit_start_row", "withdraw_start_row", "last_error", "updated_at"])
    return row


def _sheet_public(row: GoogleSheetSetting) -> dict:
    return {
        "slot": row.slot,
        "label": sheet_label(row.slot),
        "sheet_name": row.sheet_name,
        "sheet_url": row.sheet_url,
        "blocked": bool(row.blocked),
        "auto_sync": bool(row.auto_sync),
        "deposit_start_row": row.deposit_start_row or DEFAULT_DEPOSIT_START,
        "withdraw_start_row": row.withdraw_start_row or DEFAULT_WITHDRAW_START,
        "sheet_id": normalize_google_sheet_id(row.sheet_url),
        "last_error": row.last_error,
        "last_written_at": row.last_written_at.isoformat() if row.last_written_at else "",
    }


def _spreadsheet_title(sheet_id: str) -> str:
    if not sheet_id:
        return ""
    try:
        return str(_open_spreadsheet(sheet_id).title or "").strip()[:200]
    except Exception as exc:
        log.warning("Google Sheet title lookup failed: %s", str(exc).splitlines()[0][:300])
        return ""


def _fill_missing_sheet_names() -> None:
    for row in GoogleSheetSetting.objects.filter(slot__in=SHEET_SLOTS):
        if row.sheet_name or not normalize_google_sheet_id(row.sheet_url):
            continue
        title = _spreadsheet_title(normalize_google_sheet_id(row.sheet_url))
        if not title:
            continue
        GoogleSheetSetting.objects.filter(pk=row.pk, sheet_name="").update(sheet_name=title)


def public_status() -> dict:
    ensure_sheet_slots()
    _fill_missing_sheet_names()
    row = sheet_setting(1)
    sheets = [_sheet_public(item) for item in GoogleSheetSetting.objects.filter(slot__in=SHEET_SLOTS).order_by("slot")]
    return {
        "sheet_url": row.sheet_url,
        "blocked": bool(row.blocked),
        "deposit_start_row": row.deposit_start_row or DEFAULT_DEPOSIT_START,
        "withdraw_start_row": row.withdraw_start_row or DEFAULT_WITHDRAW_START,
        "sheet_id": normalize_google_sheet_id(row.sheet_url),
        "last_error": row.last_error,
        "last_written_at": row.last_written_at.isoformat() if row.last_written_at else "",
        "written_count": SheetExport.objects.count(),
        "sheets": sheets,
    }


def sync_brands_for_day(day, slot_raw=1) -> dict:
    """Write every deposit and withdrawal for the day, then compare counts with the sheet."""
    slot = _slot_number(slot_raw)
    if not _lock.acquire(timeout=180):
        raise ValueError("A Google Sheet sync is already running.")
    try:
        return _sync_brands_for_day(day, slot)
    finally:
        _lock.release()


def _sync_brands_for_day(day, slot: int) -> dict:
    row = sheet_setting(slot)
    sheet_id = normalize_google_sheet_id(row.sheet_url)
    if not sheet_id:
        raise ValueError(f"Save a link for {sheet_label(slot)} first.")
    pending = list(
        Transaction.objects.filter(
            txn_date=day,
            status="COMPLETED",
            type__in=["DEPOSIT", "WITHDRAW"],
            brand__is_active=True,
        )
        .select_related("brand")
        .order_by("created_at", "id")
    )
    spreadsheet = _open_spreadsheet(sheet_id)
    title = str(day.day)
    worksheet = next((item for item in spreadsheet.worksheets() if str(item.title).strip() == title), None)
    removed = _remove_uncompleted(worksheet, day, slot) if worksheet is not None and not _sheet_is_locked(worksheet) else 0
    _write_payment_methods(spreadsheet, day)
    written, errors = _write_cashbook(
        spreadsheet,
        pending,
        row.deposit_start_row or DEFAULT_DEPOSIT_START,
        row.withdraw_start_row or DEFAULT_WITHDRAW_START,
        slot,
    )
    if worksheet is not None:
        worksheet = next((item for item in spreadsheet.worksheets() if str(item.title).strip() == title), None)
    present = _cashbook_ids(worksheet) if worksheet is not None else set()
    wanted = {item.external_id for item in pending}
    database_count = len(wanted)
    sheet_count = len(wanted & present)
    deposits = sum(1 for item in pending if item.type == "DEPOSIT")
    withdraws = database_count - deposits
    detail = (
        f"Completed only: {deposits} deposits and {withdraws} withdrawals in the database. "
        f"{sheet_label(slot)} has {sheet_count} of those ids, each id once."
    )
    if removed:
        detail += f" Removed {removed} rows that were not completed."
    if errors:
        detail = f"{detail} {' '.join(errors)}"
    GoogleSheetSetting.objects.filter(pk=row.pk).update(
        last_error="" if sheet_count == database_count and not errors else detail[:500],
        last_written_at=timezone.now() if written else row.last_written_at,
    )
    return {
        "ok": sheet_count == database_count and not errors,
        "database_count": database_count,
        "sheet_count": sheet_count,
        "written": len(written),
        "detail": detail,
    }


def request_export() -> None:
    """Wake the sheet writer immediately. Safe to call after new completed rows are stored."""
    _wake.set()


def request_gateway_bank_patch() -> None:
    """Write AtasPay and AmoPay into the Bank column of rows already on the sheet."""
    _gateway_patch.set()
    _wake.set()


def start_writer() -> None:
    """Keep writing completed rows for as long as this process is running."""
    global _writer_started
    with _writer_guard:
        if _writer_started:
            return
        _writer_started = True
    thread = threading.Thread(target=_writer_loop, name="sheet-writer", daemon=True)
    thread.start()
    request_gateway_bank_patch()


def _writer_loop() -> None:
    while True:
        _wake.wait(timeout=1)
        _wake.clear()
        try:
            close_old_connections()
            while True:
                count = export_pending(limit=200)
                if count < 0:
                    time.sleep(0.25)
                    continue
                if count == 0:
                    break
            if _gateway_patch.is_set():
                _gateway_patch.clear()
                patch_gateway_banks()
        except Exception:
            log.exception("Google Sheet export failed")
        finally:
            close_old_connections()


def export_pending(limit: int = 200, slot=None) -> int:
    """Append rows that have not been written yet.

    Returns the number written, 0 when nothing is waiting, or -1 when another
    sheet write is already in progress. Pass slot to write only that sheet.
    """
    if not _lock.acquire(blocking=False):
        return -1
    try:
        return _export_pending(limit, None if slot is None else _slot_number(slot))
    finally:
        _lock.release()


def _export_pending(limit: int, only_slot: int | None = None) -> int:
    sheets = active_sheet_settings()
    if only_slot is not None:
        sheets = [row for row in sheets if row.slot == only_slot]
    if not sheets:
        return 0
    written_total = 0
    for row in sheets:
        deposit_start = row.deposit_start_row or DEFAULT_DEPOSIT_START
        withdraw_start = row.withdraw_start_row or DEFAULT_WITHDRAW_START
        pending = _pending_for_sheet(row.slot, limit)
        if not pending:
            continue
        try:
            spreadsheet = _open_spreadsheet(normalize_google_sheet_id(row.sheet_url))
            written, errors = _write_cashbook(spreadsheet, pending, deposit_start, withdraw_start, row.slot)
        except Exception as exc:
            message = str(exc).splitlines()[0][:500]
            log.warning("%s write failed: %s", sheet_label(row.slot), message)
            GoogleSheetSetting.objects.filter(pk=row.pk).update(last_error=message)
            continue
        GoogleSheetSetting.objects.filter(pk=row.pk).update(
            last_error=" ".join(errors)[:500],
            last_written_at=timezone.now() if written else row.last_written_at,
        )
        written_total += len(written)
    return written_total


def _pending_for_sheet(slot: int, limit: int) -> list[Transaction]:
    """Today's missing rows go out before older days, so the live count can match the sheet."""
    base = (
        Transaction.objects.filter(status="COMPLETED", type__in=["DEPOSIT", "WITHDRAW"], brand__is_active=True)
        .exclude(sheet_exports__slot=slot)
        .select_related("brand")
    )
    today = sydney_today()
    current = list(base.filter(txn_date=today).order_by("created_at", "id")[:limit])
    if len(current) >= limit:
        return current
    older = list(
        base.exclude(txn_date=today).order_by("txn_date", "created_at", "id")[: limit - len(current)]
    )
    return current + older


def _locked_sheet_ids(spreadsheet) -> set[int]:
    """Tabs with the lock icon. The whole sheet is protected, so nothing on it is edited."""
    cached = getattr(spreadsheet, "_kaboom_locked", None)
    if isinstance(cached, set):
        return cached
    locked: set[int] = set()
    try:
        meta = spreadsheet.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,protectedRanges.range)"})
    except Exception as exc:
        log.warning("Could not read sheet locks: %s", str(exc).splitlines()[0][:200])
        spreadsheet._kaboom_locked = locked
        return locked
    for sheet in meta.get("sheets") or []:
        sheet_id = (sheet.get("properties") or {}).get("sheetId")
        for rule in sheet.get("protectedRanges") or []:
            area = rule.get("range") or {}
            whole_sheet = not any(
                key in area for key in ("startRowIndex", "endRowIndex", "startColumnIndex", "endColumnIndex")
            )
            if whole_sheet and sheet_id is not None:
                locked.add(int(sheet_id))
    spreadsheet._kaboom_locked = locked
    return locked


def _sheet_is_locked(worksheet) -> bool:
    return int(worksheet.id) in _locked_sheet_ids(worksheet.spreadsheet)


def _open_spreadsheet(sheet_id: str):
    if not CREDENTIALS.is_file():
        raise FileNotFoundError(f"Service account key is missing: {CREDENTIALS}")
    import gspread

    client = gspread.service_account(filename=str(CREDENTIALS))
    return client.open_by_key(sheet_id)


def _write_cashbook(
    spreadsheet,
    pending: list[Transaction],
    deposit_start: int = DEFAULT_DEPOSIT_START,
    withdraw_start: int = DEFAULT_WITHDRAW_START,
    slot: int = 1,
) -> tuple[list[Transaction], list[str]]:
    """Finance cashbook: tab name is the transaction date's day number.

    Deposits fill empty rows from deposit_start and stop before withdraw_start.
    Withdrawals fill empty rows from withdraw_start downward. Column A and any
    row that already has an ID are not touched.
    """
    deposit_start = int(deposit_start)
    withdraw_start = int(withdraw_start)
    deposit_end = withdraw_start - 1
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
        if _sheet_is_locked(worksheet):
            continue
        try:
            ids = worksheet.col_values(7)
            existing = _cashbook_ids(worksheet)
            _clear_duplicate_ids(worksheet, ids)
            deposit_choices = _bank_dropdown(worksheet, deposit_start)
            withdraw_choices = _bank_dropdown(worksheet, withdraw_start) or deposit_choices
            _copy_owner_validation(worksheet)
            owner_choices = _owner_dropdown(worksheet)
            _clear_blank_category(worksheet, ids)
            seen: set[str] = set()
            unique_items: list[Transaction] = []
            for item in items:
                if not item.external_id or item.external_id in seen:
                    continue
                seen.add(item.external_id)
                unique_items.append(item)
            already = [item for item in unique_items if item.external_id in existing]
            fresh = [item for item in unique_items if item.external_id not in existing]
            _remember(already, slot)
            _align_existing_banks(worksheet, [item for item in already if item.type != "WITHDRAW"], deposit_choices)
            _align_existing_banks(worksheet, [item for item in already if item.type == "WITHDRAW"], withdraw_choices)
            _align_existing_owners(worksheet, already, owner_choices)
            deposits = [item for item in fresh if item.type != "WITHDRAW"]
            withdraws = [item for item in fresh if item.type == "WITHDRAW"]
            placed = _write_block(worksheet, ids, deposits, deposit_start, deposit_end, deposit_choices, owner_choices)
            needed_rows = withdraw_start + len(withdraws) + 5
            if worksheet.row_count < needed_rows:
                worksheet.add_rows(needed_rows - worksheet.row_count)
            withdraw_end = max(worksheet.row_count, needed_rows)
            placed += _write_block(worksheet, ids, withdraws, withdraw_start, withdraw_end, withdraw_choices, owner_choices)
            _remember(placed, slot)
            written.extend(already)
            written.extend(placed)
            left = len(fresh) - len(placed)
            if left:
                errors.append(f"Tab {title} ran out of empty rows for {left} transaction(s).")
        except Exception as exc:
            errors.append(f"Tab {title}: {str(exc).splitlines()[0][:180]}")
            log.warning("Google Sheet tab %s failed: %s", title, exc)
    return written, errors


def _remove_uncompleted(worksheet, day, slot: int) -> int:
    """Clear cashbook rows whose transaction is a deposit or withdrawal that is not completed."""
    unwanted = set(
        Transaction.objects.filter(txn_date=day, type__in=["DEPOSIT", "WITHDRAW"])
        .exclude(status="COMPLETED")
        .values_list("external_id", flat=True)
    )
    if not unwanted:
        return 0
    ranges = []
    cleared: list[str] = []
    for index, value in enumerate(worksheet.col_values(7), start=1):
        txn_id = str(value).strip()
        if txn_id not in unwanted:
            continue
        ranges.append({"range": f"B{index}:J{index}", "values": [["", "", "", "", "", "", "", "", ""]]})
        cleared.append(txn_id)
    for offset in range(0, len(ranges), 200):
        chunk = ranges[offset : offset + 200]
        if chunk:
            worksheet.batch_update(chunk, value_input_option="USER_ENTERED")
    if cleared:
        SheetExport.objects.filter(
            slot=slot,
            transaction__external_id__in=cleared,
            transaction__txn_date=day,
        ).delete()
    return len(cleared)


def _write_payment_methods(spreadsheet, day) -> int:
    """Put the payment method in Bank for completed rows that have no bank account."""
    items = list(
        Transaction.objects.filter(
            txn_date=day,
            status="COMPLETED",
            type__in=["DEPOSIT", "WITHDRAW"],
            bank_name="",
            bank_account_name="",
        )
        .exclude(method="")
        .only("external_id", "method", "txn_date")
    )
    if not items:
        return 0
    title = str(day.day)
    worksheet = next((item for item in spreadsheet.worksheets() if str(item.title).strip() == title), None)
    if worksheet is None or _sheet_is_locked(worksheet):
        return 0
    positions: dict[str, int] = {}
    for index, value in enumerate(worksheet.col_values(7), start=1):
        key = str(value).strip()
        if key and key not in positions:
            positions[key] = index
    ranges = []
    for item in items:
        slot = positions.get(item.external_id)
        if slot is None:
            continue
        ranges.append({"range": f"C{slot}", "values": [[_match_bank(item.method.strip(), _bank_dropdown(worksheet))]]})
    for offset in range(0, len(ranges), 200):
        chunk = ranges[offset : offset + 200]
        if chunk:
            worksheet.batch_update(chunk, value_input_option="USER_ENTERED")
    return len(ranges)


def _cashbook_ids(worksheet) -> set[str]:
    """Transaction ids already on this tab. Bank-summary numbers in column G are not ids."""
    found: set[str] = set()
    for row in worksheet.get("F:G"):
        status = str(row[0]).strip() if row else ""
        txn_id = str(row[1]).strip() if len(row) > 1 else ""
        if status in {"Deposit", "Withdraw"} and txn_id:
            found.add(txn_id)
    return found


def _clear_duplicate_ids(worksheet, id_column: list[str]) -> None:
    """Blank a later cashbook row when its transaction id is already on an earlier row."""
    seen: dict[str, int] = {}
    ranges = []
    for index, value in enumerate(id_column, start=1):
        txn_id = str(value).strip()
        if not txn_id or not txn_id.isdigit():
            continue
        if txn_id in seen:
            ranges.append({"range": f"B{index}:J{index}", "values": [["", "", "", "", "", "", "", "", ""]]})
            id_column[index - 1] = ""
            continue
        seen[txn_id] = index
    for offset in range(0, len(ranges), 200):
        chunk = ranges[offset : offset + 200]
        if chunk:
            worksheet.batch_update(chunk, value_input_option="USER_ENTERED")


def _remember(items: list[Transaction], slot: int = 1) -> None:
    if items:
        SheetExport.objects.bulk_create(
            [SheetExport(transaction=item, slot=slot) for item in items],
            ignore_conflicts=True,
        )


def _write_block(
    worksheet,
    id_column: list[str],
    items: list[Transaction],
    start: int,
    end: int,
    bank_choices: list[str] | None = None,
    owner_choices: list[str] | None = None,
):
    if not items:
        return []
    slots = _empty_slots(id_column, start, end, len(items))
    if not slots:
        return []
    batch = items[: len(slots)]
    ranges = []
    run_start = slots[0]
    run_values = [_cashbook_cells(batch[0], bank_choices, owner_choices)]
    for index in range(1, len(slots)):
        if slots[index] == slots[index - 1] + 1:
            run_values.append(_cashbook_cells(batch[index], bank_choices, owner_choices))
            continue
        ranges.append((run_start, run_values))
        run_start = slots[index]
        run_values = [_cashbook_cells(batch[index], bank_choices, owner_choices)]
    ranges.append((run_start, run_values))
    # Column I is the Category dropdown. Writing a blank there is what Sheets marks invalid.
    worksheet.batch_update(
        [
            item
            for start_row, values in ranges
            for item in (
                {
                    "range": f"B{start_row}:H{start_row + len(values) - 1}",
                    "values": [row[:7] for row in values],
                },
                {
                    "range": f"J{start_row}:J{start_row + len(values) - 1}",
                    "values": [[row[8]] for row in values],
                },
            )
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


def patch_gateway_banks() -> int:
    """Put the payment method in column C for AtasPay and AmoPay rows. Other rows are not changed."""
    from brands.models import is_gateway_method

    if not _lock.acquire(blocking=False):
        _gateway_patch.set()
        return -1
    try:
        sheets = active_sheet_settings()
        if not sheets:
            return 0
        items = [
            item
            for item in Transaction.objects.filter(
                status="COMPLETED",
                type__in=["DEPOSIT", "WITHDRAW"],
            )
            .exclude(method="")
            .only("external_id", "method", "txn_date")
            if is_gateway_method(item.method)
        ]
        if not items:
            return 0
        updated = 0
        for row in sheets:
            spreadsheet = _open_spreadsheet(normalize_google_sheet_id(row.sheet_url))
            tabs = {str(worksheet.title).strip(): worksheet for worksheet in spreadsheet.worksheets()}
            grouped: dict[str, list[Transaction]] = {}
            for item in items:
                grouped.setdefault(_tab_name(item), []).append(item)
            updated += _patch_gateway_tabs(tabs, grouped)
        return updated
    except Exception as exc:
        message = str(exc).splitlines()[0][:500]
        log.warning("Google Sheet payment-method update failed: %s", message)
        return 0
    finally:
        _lock.release()


def _patch_gateway_tabs(tabs, grouped: dict[str, list[Transaction]]) -> int:
    updated = 0
    for title, group in grouped.items():
        worksheet = tabs.get(title)
        if worksheet is None or _sheet_is_locked(worksheet):
            continue
        positions: dict[str, tuple[int, str]] = {}
        for index, cells in enumerate(worksheet.get("C:G"), start=1):
            txn_id = str(cells[4]).strip() if len(cells) > 4 else ""
            if not txn_id or txn_id in positions:
                continue
            current = str(cells[0]).strip() if cells else ""
            positions[txn_id] = (index, current)
        ranges = []
        for item in group:
            found = positions.get(item.external_id)
            if found is None:
                continue
            row_number, current = found
            method = item.method.strip()
            if not method or current == method:
                continue
            ranges.append({"range": f"C{row_number}", "values": [[_match_bank(method, _bank_dropdown(worksheet))]]})
        for offset in range(0, len(ranges), 200):
            chunk = ranges[offset : offset + 200]
            if chunk:
                worksheet.batch_update(chunk, value_input_option="USER_ENTERED")
                updated += len(chunk)
    return updated


def _bank_dropdown(worksheet, around_row: int = 105) -> list[str]:
    """Dropdown entries for the Bank column around a deposit or withdrawal row."""
    cached = getattr(worksheet, "_kaboom_banks", None)
    if not isinstance(cached, dict):
        cached = {}
        worksheet._kaboom_banks = cached
    key = max(2, int(around_row))
    if key not in cached:
        cached[key] = _read_dropdown(worksheet, "C", key, key + 30)
    return cached[key]


def _read_bank_dropdown(worksheet, start_row: int = 105, end_row: int = 135) -> list[str]:
    return _read_dropdown(worksheet, "C", start_row, end_row)


def _read_dropdown(worksheet, column: str, start_row: int = 105, end_row: int = 135) -> list[str]:
    title = str(worksheet.title).replace("'", "''")
    column = str(column or "C").upper()
    start_row = max(2, int(start_row))
    end_row = max(start_row, int(end_row))
    try:
        meta = worksheet.spreadsheet.fetch_sheet_metadata(
            {
                "includeGridData": True,
                "ranges": [f"'{title}'!{column}{start_row}:{column}{end_row}"],
                "fields": "sheets.data.rowData.values.dataValidation",
            }
        )
    except Exception as exc:
        log.warning("Bank dropdown lookup failed: %s", str(exc).splitlines()[0][:300])
        return []
    rule = None
    for sheet in meta.get("sheets") or []:
        for grid in sheet.get("data") or []:
            for row in grid.get("rowData") or []:
                for cell in row.get("values") or []:
                    found = cell.get("dataValidation")
                    if found:
                        rule = found
                        break
                if rule:
                    break
            if rule:
                break
        if rule:
            break
    if not rule:
        return []
    condition = rule.get("condition") or {}
    raw_values = [str(item.get("userEnteredValue") or "").strip() for item in condition.get("values") or []]
    raw_values = [item for item in raw_values if item]
    kind = condition.get("type")
    if kind == "ONE_OF_LIST":
        return raw_values
    if kind == "ONE_OF_RANGE" and raw_values:
        return _dropdown_range_values(worksheet.spreadsheet, raw_values[0])
    return []


def _dropdown_range_values(spreadsheet, raw: str) -> list[str]:
    ref = str(raw or "").strip().lstrip("=")
    if not ref:
        return []
    try:
        result = spreadsheet.values_get(ref)
    except Exception as exc:
        log.warning("Bank dropdown range failed: %s", str(exc).splitlines()[0][:300])
        return []
    found: list[str] = []
    seen: set[str] = set()
    for row in result.get("values") or []:
        for cell in row:
            text = str(cell).strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                found.append(text)
    return found


def _bank_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())


def _bank_tokens(text: str) -> tuple[str, ...]:
    return tuple(sorted(part for part in re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).split() if part))


_BANK_SUFFIXES = {"au", "nz", "uk", "us", "sg"}


def _token_gap(left: str, right: str) -> int | None:
    """0 when the words are the same. A small gap when one is the other plus a country code, as in ING and INGAU."""
    if left == right:
        return 0
    longer, shorter = (left, right) if len(left) >= len(right) else (right, left)
    if len(shorter) < 2 or not longer.startswith(shorter):
        return None
    extra = longer[len(shorter) :]
    if extra in _BANK_SUFFIXES:
        return len(extra)
    return None


def _dropdown_score(label: str, choice: str) -> int | None:
    label_tokens = _bank_tokens(label)
    choice_tokens = list(_bank_tokens(choice))
    if not label_tokens or len(label_tokens) != len(choice_tokens):
        return None
    score = 0
    for token in label_tokens:
        found = None
        best = 99
        for index, other in enumerate(choice_tokens):
            gap = _token_gap(token, other)
            if gap is None or gap >= best:
                continue
            best = gap
            found = index
        if found is None:
            return None
        score += best
        choice_tokens.pop(found)
    return score


def _gateway_dropdown(label: str, choices: list[str]) -> str:
    """AmoPayRamp uses the AMOPAY dropdown entry. AtasPay uses the AtasPay entry."""
    compact = _bank_key(label)
    needle = "amopay" if "amopay" in compact else "ataspay" if "ataspay" in compact else ""
    if not needle:
        return ""
    exact = [choice for choice in choices if _bank_key(choice) == needle]
    if exact:
        return exact[0]
    contains = [choice for choice in choices if needle in _bank_key(choice)]
    if not contains:
        return ""
    return min(contains, key=lambda choice: len(_bank_key(choice)))


def _match_bank(label: str, choices: list[str]) -> str:
    """Return the dropdown entry for this bank. The cell is then that list value, not a free-typed name.

    ANZ JOSEPH PERERA matches Joseph Perera anz. INGAU SZE LIN LAU matches ING SZE LIN LAU.
    """
    text = str(label or "").strip()
    if not text or not choices:
        return text
    gateway = _gateway_dropdown(text, choices)
    if gateway:
        return gateway
    best_choice = ""
    best_score = None
    for choice in choices:
        if choice.strip() == text:
            return choice
        score = 0 if _bank_key(choice) == _bank_key(text) else _dropdown_score(text, choice)
        if score is None:
            continue
        if best_score is None or score < best_score:
            best_score = score
            best_choice = choice
    return best_choice or text


def _align_existing_banks(worksheet, items: list[Transaction], choices: list[str]) -> None:
    """Point Bank cells already on this tab at the matching dropdown entry. Other columns stay as they are."""
    if not items or not choices:
        return
    banks = worksheet.col_values(3)
    ids = worksheet.col_values(7)
    positions: dict[str, int] = {}
    for index, value in enumerate(ids, start=1):
        key = str(value).strip()
        if key and key not in positions:
            positions[key] = index
    ranges = []
    for item in items:
        row_number = positions.get(item.external_id)
        if row_number is None:
            continue
        current = banks[row_number - 1].strip() if row_number - 1 < len(banks) else ""
        matched = _match_bank(_sheet_bank(item), choices)
        if not matched or current == matched:
            continue
        ranges.append({"range": f"C{row_number}", "values": [[matched]]})
    for offset in range(0, len(ranges), 200):
        chunk = ranges[offset : offset + 200]
        if chunk:
            worksheet.batch_update(chunk, value_input_option="USER_ENTERED")


def _sheet_bank(item: Transaction) -> str:
    """Bank column is the bank name plus account name, or the payment method for AtasPay and AmoPay."""
    from brands.models import is_gateway_method

    if is_gateway_method(item.method):
        return (item.method or "").strip()
    bank = (item.bank_name or "").strip()
    account = (item.bank_account_name or "").strip()
    label = " ".join(part for part in (bank, account) if part)
    if label:
        return label
    return (item.method or "").strip()


OWNER_COLUMN = 8
OWNER_VALID_ROW = 428


def _owner_dropdown(worksheet) -> list[str]:
    """Company Owner entries from the row the sheet already accepts as valid."""
    choices = _read_dropdown(worksheet, "H", OWNER_VALID_ROW, OWNER_VALID_ROW + 20)
    if choices:
        return choices
    return _read_dropdown(worksheet, "H", 105, 140)


def _validation_rule(worksheet, column: str, row: int) -> dict | None:
    title = str(worksheet.title).replace("'", "''")
    meta = worksheet.spreadsheet.fetch_sheet_metadata(
        {
            "includeGridData": True,
            "ranges": [f"'{title}'!{column}{row}"],
            "fields": "sheets.data.rowData.values.dataValidation",
        }
    )
    for sheet in meta.get("sheets") or []:
        for grid in sheet.get("data") or []:
            for grid_row in grid.get("rowData") or []:
                for cell in grid_row.get("values") or []:
                    rule = cell.get("dataValidation")
                    if rule and rule.get("condition"):
                        return rule
    return None


def _copy_owner_validation(worksheet) -> None:
    """Rows above 428 use another list, so the same Company Owner is marked invalid there.

    Apply the exact row-428 rule, including its range, to those earlier rows.
    """
    rule = _validation_rule(worksheet, "H", OWNER_VALID_ROW)
    if not rule:
        return
    try:
        worksheet.spreadsheet.batch_update(
            {
                "requests": [
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": worksheet.id,
                                "startRowIndex": 1,
                                "endRowIndex": OWNER_VALID_ROW - 1,
                                "startColumnIndex": OWNER_COLUMN - 1,
                                "endColumnIndex": OWNER_COLUMN,
                            },
                            "rule": rule,
                        }
                    }
                ]
            }
        )
    except Exception as exc:
        log.warning("Company Owner dropdown update failed: %s", str(exc).splitlines()[0][:300])


def _clear_blank_category(worksheet, id_column: list[str]) -> None:
    """A blank written into the Category dropdown is rejected. Remove only those blanks."""
    categories = worksheet.col_values(9)
    targets = []
    for index, txn in enumerate(id_column, start=1):
        if not str(txn).strip().isdigit():
            continue
        if index - 1 >= len(categories):
            break
        if str(categories[index - 1]).strip():
            continue
        targets.append(f"I{index}")
    for offset in range(0, len(targets), 200):
        chunk = targets[offset : offset + 200]
        if chunk:
            worksheet.batch_clear(chunk)


def _align_existing_owners(worksheet, items: list[Transaction], choices: list[str]) -> None:
    """Set Company Owner to the dropdown entry. Bank and the other columns stay as they are."""
    if not items or not choices:
        return
    owners = worksheet.col_values(OWNER_COLUMN)
    ids = worksheet.col_values(7)
    positions: dict[str, int] = {}
    for index, value in enumerate(ids, start=1):
        key = str(value).strip()
        if key and key not in positions:
            positions[key] = index
    ranges = []
    for item in items:
        row_number = positions.get(item.external_id)
        if row_number is None:
            continue
        current = owners[row_number - 1].strip() if row_number - 1 < len(owners) else ""
        matched = _match_bank(item.brand.name, choices)
        if not matched or current == matched:
            continue
        ranges.append({"range": f"H{row_number}", "values": [[matched]]})
    for offset in range(0, len(ranges), 200):
        chunk = ranges[offset : offset + 200]
        if chunk:
            worksheet.batch_update(chunk, value_input_option="USER_ENTERED")


def _cashbook_cells(item: Transaction, bank_choices: list[str] | None = None, owner_choices: list[str] | None = None) -> list[str]:
    """B Date through J Player. Column A, Rate, and Staff are never written."""
    amount = f"{abs(item.amount):.2f}"
    status = "Withdraw" if item.type == "WITHDRAW" else "Deposit"
    if item.type == "WITHDRAW":
        amount = f"-{amount}"
    return [
        _when(item),
        _match_bank(_sheet_bank(item), bank_choices or []),
        (item.player_name or "").strip(),
        amount,
        status,
        item.external_id,
        _match_bank(item.brand.name, owner_choices or []),
        "",
        item.username,
    ]


def repair_written_columns() -> int:
    """Correct Bank and Description on rows this app already wrote. Staff is not touched."""
    sheets = active_sheet_settings()
    if not sheets:
        return 0
    updated = 0
    for row in sheets:
        exported = list(
            SheetExport.objects.filter(slot=row.slot)
            .select_related("transaction", "transaction__brand")
            .order_by("transaction__txn_date", "id")
        )
        if not exported:
            continue
        spreadsheet = _open_spreadsheet(normalize_google_sheet_id(row.sheet_url))
        tabs = {str(worksheet.title).strip(): worksheet for worksheet in spreadsheet.worksheets()}
        grouped: dict[str, list[Transaction]] = {}
        for mark in exported:
            grouped.setdefault(_tab_name(mark.transaction), []).append(mark.transaction)
        for title, items in grouped.items():
            worksheet = tabs.get(title)
            if worksheet is None or _sheet_is_locked(worksheet):
                continue
            ids = worksheet.col_values(7)
            positions = {}
            for index, value in enumerate(ids, start=1):
                key = str(value).strip()
                if key and key not in positions:
                    positions[key] = index
            ranges = []
            for item in items:
                row_number = positions.get(item.external_id)
                if row_number is None:
                    continue
                ranges.append(
                    {
                        "range": f"C{row_number}:D{row_number}",
                        "values": [[_match_bank(_sheet_bank(item), _bank_dropdown(worksheet)), (item.player_name or "").strip()]],
                    }
                )
            for offset in range(0, len(ranges), 200):
                chunk = ranges[offset : offset + 200]
                if chunk:
                    worksheet.batch_update(chunk, value_input_option="USER_ENTERED")
                    updated += len(chunk)
    return updated


def clear_exports_for_tests() -> None:
    with db_transaction.atomic():
        SheetExport.objects.all().delete()
