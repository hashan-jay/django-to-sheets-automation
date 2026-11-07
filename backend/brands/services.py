"""Read each brand transaction API and store one row per transaction id."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

import requests
from django.db import close_old_connections, transaction
from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from brands import livecache
from brands.models import SYDNEY, BankLedgerSetting, BankTransfer, Brand, BrandSync, CompanyBank, Transaction, _clock, sydney_today

UTC = ZoneInfo("UTC")

LIVE_STATUSES = ("PENDING", "COMPLETED", "REJECTED")
_TAG_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.I)
_HTML_RE = re.compile(r"<[^>]+>")
_lock = threading.Lock()
_cache_lock = threading.Lock()
_bank_status_lock = threading.Lock()
_BANK_STATUS_TTL = 30.0
_bank_status_cache: dict[int, tuple[float, set[tuple[str, str]]]] = {}
_cache: dict[tuple[str, str, str], dict] = {}
_http_local = threading.local()
_TRANSIENT = {"ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout"}


def sync_day(day: date, *, wait: bool = True) -> None:
    acquired = _lock.acquire(blocking=wait)
    if not acquired:
        return
    try:
        _sync_day(day)
    finally:
        _lock.release()


def _sync_day(day: date) -> None:
    close_old_connections()
    try:
        brands = list(Brand.objects.filter(is_active=True))
        close_old_connections()
        fetched = _fetch_brands(brands, day)
        harvested: dict[str, tuple[str, str]] = {}
        for _brand, rows, _errors in fetched:
            harvested.update(_harvest_banks(rows))
        if harvested:
            _save_company_banks(harvested)
        catalog = {item.external_id: item.account_name for item in CompanyBank.objects.all()}
        changed = False
        for brand, rows, errors in fetched:
            if rows and _store_rows(brand, day, rows, catalog):
                changed = True
            if _save_sync(brand, day, " ".join(errors), len(rows)):
                changed = True
        if changed or not livecache.has_snapshot(day):
            publish_snapshot(day)
    finally:
        close_old_connections()


def _fetch_brands(brands: list[Brand], day: date) -> list[tuple[Brand, list[dict], list[str]]]:
    if not brands:
        return []

    def collect(brand: Brand) -> tuple[Brand, list[dict], list[str]]:
        try:
            rows, errors = _collect_brand(brand, day)
            return brand, rows, errors
        except Exception as exc:
            return brand, [], [f"{brand.name}: {exc.__class__.__name__}"]
        finally:
            close_old_connections()

    workers = min(8, len(brands))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="brand-fetch") as pool:
        return list(pool.map(collect, brands))


def _collect_brand(brand: Brand, day: date) -> tuple[list[dict], list[str]]:
    if not brand.token:
        return [], [f"{brand.name} has no token"]
    if not brand.merchant_id:
        return [], [f"{brand.name} merchant id is not set"]
    collected: list[dict] = []
    errors: list[str] = []
    day_text = day.isoformat()
    pending_key = (brand.name, "PENDING", day_text)
    previous = _cache_get(pending_key)
    previous_ids = _ids(previous.get("raw", []) if previous else [])
    pending_raw, pending_error = _read_status(brand, day_text, "PENDING", force_full=True)
    if pending_error:
        errors.append(f"{brand.name} PENDING: {pending_error}")
    collected.extend(pending_raw)
    pending_changed = previous_ids != _ids(pending_raw)
    for status in ("COMPLETED", "REJECTED"):
        raw, error = _read_status(brand, day_text, status, force_full=pending_changed)
        if error:
            errors.append(f"{brand.name} {status}: {error}")
        collected.extend(raw)
    for kind in ("DEPOSIT", "WITHDRAW"):
        raw, error = _read_typed(brand, day_text, "COMPLETED", kind, force_full=pending_changed)
        if error:
            errors.append(f"{brand.name} COMPLETED {kind}: {error}")
        collected.extend(raw)
    for status in ("COMPLETED", "PENDING", "REJECTED"):
        raw, error = _read_typed(
            brand,
            day_text,
            status,
            "FORFEITED",
            force_full=pending_changed,
            max_pages=250,
        )
        if error:
            errors.append(f"{brand.name} {status} FORFEITED: {error}")
        collected.extend(raw)
    return collected, errors


def _read_status(brand: Brand, day: str, status: str, force_full: bool = False) -> tuple[list[dict], str]:
    key = (brand.name, status, day)
    try:
        if status == "PENDING":
            raw, error, total = fetch_brand(brand, day, status, max_pages=10)
            if not error:
                _cache_put(key, {"sig": (total, ""), "raw": raw})
        else:
            raw, error, total = fetch_brand(brand, day, status, max_pages=1)
            head = str(raw[0].get("id") or "") if raw else ""
            cached = _cache_get(key)
            unchanged = cached and cached["sig"] == (total, head) and total <= len(cached["raw"])
            if not error and not force_full and unchanged:
                raw = cached["raw"]
            elif not error and (force_full or total > len(raw)):
                raw, error, total = fetch_brand(brand, day, status, max_pages=40)
                head = str(raw[0].get("id") or "") if raw else ""
            if not error:
                _cache_put(key, {"sig": (total, head), "raw": raw})
    except requests.RequestException as exc:
        error = exc.__class__.__name__
        raw = []
    except ValueError:
        error = "The brand API did not return JSON"
        raw = []
    if error in _TRANSIENT:
        cached = _cache_get(key)
        if cached and cached.get("raw"):
            return list(cached["raw"]), ""
    if error:
        cached = _cache_get(key)
        if cached:
            raw = cached["raw"]
    return raw, error


def _read_typed(
    brand: Brand,
    day: str,
    status: str,
    txn_type: str,
    force_full: bool = False,
    max_pages: int = 40,
) -> tuple[list[dict], str]:
    """Completed deposits and withdrawals are paged separately so bank names are not cut off."""
    key = (brand.name, f"{status}:{txn_type}", day)
    try:
        raw, error, total = fetch_brand(brand, day, status, max_pages=1, txn_type=txn_type)
        head = str(raw[0].get("id") or "") if raw else ""
        cached = _cache_get(key)
        unchanged = (
            not force_full
            and cached is not None
            and cached["sig"] == (total, head)
            and total <= len(cached["raw"])
        )
        if not error and unchanged:
            raw = cached["raw"]
        elif not error and (force_full or total > len(raw)):
            raw, error, total = fetch_brand(brand, day, status, max_pages=max_pages, txn_type=txn_type)
            head = str(raw[0].get("id") or "") if raw else ""
        if not error:
            _cache_put(key, {"sig": (total, head), "raw": raw})
    except requests.RequestException as exc:
        error = exc.__class__.__name__
        raw = []
    except ValueError:
        error = "The brand API did not return JSON"
        raw = []
    if error in _TRANSIENT:
        cached = _cache_get(key)
        if cached and cached.get("raw"):
            return list(cached["raw"]), ""
    return raw, error


def _http() -> requests.Session:
    session = getattr(_http_local, "session", None)
    if session is None:
        session = requests.Session()
        _http_local.session = session
    return session


def _reset_http() -> None:
    session = getattr(_http_local, "session", None)
    _http_local.session = None
    if session is not None:
        try:
            session.close()
        except requests.RequestException:
            pass


def _post(url: str, form: dict) -> requests.Response:
    """Retry a dropped connection. Brand hosts close idle sockets without warning."""
    last: requests.RequestException | None = None
    for attempt in range(3):
        try:
            return _http().post(url, data=form, timeout=(5, 25))
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            _reset_http()
            time.sleep(0.35 * (attempt + 1))
    assert last is not None
    raise last


def fetch_brand(brand: Brand, day: str, status: str, max_pages: int, txn_type: str = "") -> tuple[list[dict], str, int]:
    url = brand.domain.rstrip("/") + "/api/v1/index.php"
    rows: list[dict] = []
    total = 0
    page = 0
    while page < max_pages:
        form = {
            "module": "/transactions/getAllTransactions",
            "accessId": brand.access_id,
            "accessToken": brand.token,
            "merchantId": brand.merchant_id,
            "pageIndex": str(page),
            "status": status,
            "sDate": f"{day} 00:00:00",
            "eDate": f"{day} 23:59:59",
        }
        if txn_type:
            form["type"] = txn_type
            form["pageSize"] = "100"
        response = _post(url, form)
        body = response.json()
        if str(body.get("status") or "") != "SUCCESS":
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            message = str(data.get("message") or "") or "The brand API refused the request"
            return rows, message, total
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        total = int(data.get("totalCount") or 0)
        batch = data.get("transactions") if isinstance(data.get("transactions"), list) else []
        rows.extend(item for item in batch if isinstance(item, dict))
        total_page = int(data.get("totalPage") or 1)
        if not batch or page + 1 >= total_page:
            break
        page += 1
    return rows, "", total


def _store_rows(brand: Brand, day: date, raw_rows: list[dict], catalog: dict[str, str] | None = None) -> bool:
    prepared = []
    for raw in raw_rows:
        external_id = str(raw.get("id") or "").strip()
        if not external_id:
            continue
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        bank = _bank(user.get("bank"))
        tags = _TAG_RE.findall(str(user.get("name") or ""))
        extra = ", ".join(tags)
        detail = " · ".join(part for part in (extra, _detail(raw)) if part)
        created = _parse_dt(raw.get("createdDateTime"))
        processed = _parse_dt(raw.get("processedDateTime"))
        prepared.append(
            Transaction(
                brand=brand,
                external_id=external_id,
                txn_date=day,
                status=str(raw.get("status") or ""),
                type=str(raw.get("type") or ""),
                amount=_money(raw.get("cash")),
                username=str(user.get("username") or "")[:128],
                player_name=str(user.get("originalName") or _HTML_RE.sub("", str(user.get("name") or "")))[:255],
                mobile=str(user.get("mobile") or "")[:64],
                bank=str(bank.get("bank") or "")[:128],
                bank_name=_selected_bank_name(raw),
                bank_account_name=_bank_account_name(raw, catalog or {}),
                acc_name=str(bank.get("bankAccountName") or "")[:255],
                acc_no=str(bank.get("bankAccountNumber") or "")[:64],
                bsb=str(bank.get("bankBSB") or "")[:32],
                pay_id=str(bank.get("payID") or "")[:128],
                method=_method(raw)[:128],
                detail=detail,
                created_at=created,
                processed_at=processed,
            )
        )
    if not prepared:
        return False
    prepared = list({item.external_id: item for item in prepared}.values())
    signature = _signature(prepared)
    signature_key = f"brands:sig:{brand.pk}:{day.isoformat()}"
    if livecache.same(signature_key, signature):
        return False
    with transaction.atomic():
        Transaction.objects.bulk_create(
            prepared,
            update_conflicts=True,
            unique_fields=["brand", "external_id"],
            update_fields=[
                "txn_date",
                "status",
                "type",
                "amount",
                "username",
                "player_name",
                "mobile",
                "bank",
                "bank_name",
                "bank_account_name",
                "acc_name",
                "acc_no",
                "bsb",
                "pay_id",
                "method",
                "detail",
                "created_at",
                "processed_at",
            ],
        )
    livecache.store(signature_key, signature)
    return True


def _selected_bank_name(raw: dict) -> str:
    """Bank chosen in the brand backend when a deposit or withdrawal is completed."""
    if str(raw.get("status") or "") != "COMPLETED":
        return ""
    if str(raw.get("type") or "") not in {"DEPOSIT", "WITHDRAW"}:
        return ""
    details = raw.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            return ""
    if not isinstance(details, dict):
        return ""
    return str(details.get("bank") or "")[:128]


def _clean_label(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _org_bank(raw: dict) -> dict:
    bank = raw.get("bank")
    if isinstance(bank, str):
        bank = _bank(bank)
    return bank if isinstance(bank, dict) else {}


def _harvest_banks(raw_rows: list[dict]) -> dict[str, tuple[str, str]]:
    """Bank id -> (bank code, organization account name) from rows that include the account."""
    found: dict[str, tuple[str, str]] = {}
    for raw in raw_rows:
        if str(raw.get("status") or "") != "COMPLETED":
            continue
        if str(raw.get("type") or "") not in {"DEPOSIT", "WITHDRAW"}:
            continue
        bank = _org_bank(raw)
        account_name = _clean_label(bank.get("accountName"))
        bank_id = str(bank.get("id") or raw.get("bankId") or "").strip()
        if not account_name or not bank_id or bank_id in {"0", "None"}:
            continue
        found[bank_id] = (str(bank.get("bankName") or "")[:128], account_name[:255])
    return found


def _save_company_banks(found: dict[str, tuple[str, str]]) -> None:
    CompanyBank.objects.bulk_create(
        [
            CompanyBank(external_id=bank_id, bank_name=bank_name, account_name=account_name)
            for bank_id, (bank_name, account_name) in found.items()
        ],
        update_conflicts=True,
        unique_fields=["external_id"],
        update_fields=["bank_name", "account_name"],
    )


def _bank_account_name(raw: dict, catalog: dict[str, str]) -> str:
    """Organization account that received a deposit or paid a withdrawal."""
    if str(raw.get("status") or "") != "COMPLETED":
        return ""
    if str(raw.get("type") or "") not in {"DEPOSIT", "WITHDRAW"}:
        return ""
    account_name = _clean_label(_org_bank(raw).get("accountName"))
    if account_name:
        return account_name[:255]
    bank_id = str(raw.get("bankId") or "").strip()
    if not bank_id or bank_id in {"0", "None"}:
        return ""
    return str(catalog.get(bank_id) or "")[:255]


def _bank(value: object) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_dt(value: object):
    """Keep the brand API instant. createdDateTime arrives as UTC, for example 2026-10-03T05:26:41+00:00."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        compact = text.replace("T", " ")
        for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
            try:
                parsed = datetime.strptime(compact[:size], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if timezone.is_naive(parsed):
        return parsed.replace(tzinfo=UTC)
    return parsed


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _method(raw: dict) -> str:
    details = raw.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            return ""
    if isinstance(details, dict):
        return str(details.get("method") or "")
    return ""


def _detail(raw: dict) -> str:
    promotion = raw.get("promotion")
    if isinstance(promotion, dict) and promotion.get("name"):
        return str(promotion["name"])
    return _method(raw)


def _ids(raw: object) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {str(item.get("id") or "") for item in raw if isinstance(item, dict) and item.get("id")}


def _cache_get(key: tuple[str, str, str]) -> dict | None:
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: tuple[str, str, str], value: dict) -> None:
    with _cache_lock:
        _cache[key] = value


def _signature(prepared: list[Transaction]) -> str:
    lines = []
    for item in sorted(prepared, key=lambda txn: txn.external_id):
        created = item.created_at.isoformat() if item.created_at else ""
        processed = item.processed_at.isoformat() if item.processed_at else ""
        lines.append(
            "|".join(
                (
                    item.external_id,
                    item.status,
                    item.type,
                    format(item.amount, "f"),
                    item.username,
                    item.player_name,
                    item.mobile,
                    item.bank,
                    item.bank_name,
                    item.bank_account_name,
                    item.acc_name,
                    item.acc_no,
                    item.bsb,
                    item.pay_id,
                    item.method,
                    item.detail,
                    created,
                    processed,
                )
            )
        )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _save_sync(brand: Brand, day: date, message: str, row_count: int) -> bool:
    state = f"{row_count}\n{message}"
    key = f"brands:sync:{brand.pk}:{day.isoformat()}"
    if livecache.same(key, state):
        return False
    BrandSync.objects.update_or_create(
        brand=brand,
        day=day,
        defaults={"message": message, "row_count": row_count},
    )
    livecache.store(key, state)
    return True


def load_dashboard(day: date) -> dict:
    packed = livecache.snapshot(day)
    if packed is not None:
        return packed
    return publish_snapshot(day)


def publish_snapshot(day: date) -> dict:
    marker = timezone.now().isoformat()
    rows, brands = _read_day(day)
    livecache.publish(day, rows, brands, marker)
    fresh = livecache.snapshot(day)
    if fresh is not None:
        return fresh
    return {"rows": rows, "brands": brands, "revision": None}


def _sydney_bounds(day: date) -> tuple[datetime, datetime]:
    """The same Sydney calendar day the dashboard uses for created time."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=SYDNEY)
    end = start + timedelta(days=1)
    return start, end


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


LEDGER_STATUSES = ("Block", "Withdraw only", "Deposit only", "Both", "Active", "Inactive")
_MONEY_FIELD = DecimalField(max_digits=16, decimal_places=2)
_LEDGER_ZERO_COLUMNS = {
    "transfer_in": "0.00",
    "pending": "0.00",
    "complete": "0.00",
    "transfer_out": "0.00",
    "cash_in": "0.00",
    "cash_out": "0.00",
}


def _bank_key(bank_name: str, account_name: str) -> tuple[str, str]:
    return (
        " ".join(str(bank_name or "").casefold().split()),
        " ".join(str(account_name or "").casefold().split()),
    )


def _active_bank_keys(brand: Brand | None = None, brands: list[Brand] | None = None) -> set[tuple[str, str]]:
    """Bank code and account name pairs the finance API currently marks ACTIVE.

    Each brand's /banks/getBank list has one active account. A group or every
    brand is combined when the sheet is not filtered to a single brand. A short
    cache keeps the ledger from calling every brand on each refresh.
    """
    if brand is not None:
        brands = [brand]
    elif brands is None:
        brands = list(Brand.objects.filter(is_active=True))
    now = time.monotonic()
    keys: set[tuple[str, str]] = set()
    stale: list[Brand] = []
    with _bank_status_lock:
        for item in brands:
            cached = _bank_status_cache.get(item.pk)
            if cached and now - cached[0] < _BANK_STATUS_TTL:
                keys |= cached[1]
            else:
                stale.append(item)
    if not stale:
        return keys
    loaded = _load_active_banks(stale)
    with _bank_status_lock:
        for item in stale:
            fresh = loaded.get(item.pk)
            if fresh is None:
                previous = _bank_status_cache.get(item.pk)
                if previous:
                    keys |= previous[1]
                continue
            _bank_status_cache[item.pk] = (time.monotonic(), fresh)
            keys |= fresh
    return keys


def _load_active_banks(brands: list[Brand]) -> dict[int, set[tuple[str, str]] | None]:
    def load(item: Brand) -> tuple[int, set[tuple[str, str]] | None]:
        close_old_connections()
        try:
            return item.pk, _fetch_active_banks(item)
        except (requests.RequestException, ValueError, TypeError):
            return item.pk, None

    if len(brands) == 1:
        brand_id, keys = load(brands[0])
        return {brand_id: keys}
    workers = min(8, len(brands))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bank-status") as pool:
        return dict(pool.map(load, brands))


def _fetch_active_banks(brand: Brand) -> set[tuple[str, str]]:
    if not brand.domain or not brand.token or not brand.merchant_id:
        return set()
    url = brand.domain.rstrip("/") + "/api/v1/index.php"
    response = _post(
        url,
        {
            "module": "/banks/getBank",
            "accessId": brand.access_id,
            "accessToken": brand.token,
            "merchantId": brand.merchant_id,
        },
    )
    body = response.json()
    if str(body.get("status") or "") != "SUCCESS":
        raise ValueError("The brand bank list was refused")
    data = body.get("data")
    rows = data if isinstance(data, list) else []
    active: set[tuple[str, str]] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().upper() != "ACTIVE":
            continue
        code = str(item.get("code") or "").strip()
        account = str(item.get("accountName") or "").strip()
        if code and account:
            active.add(_bank_key(code, account))
    return active


def bank_ledger(day: date, brand_name: str = "All", group_name: str = "All") -> dict:
    """Bank accounts for the selected group and brand.

    Opening balance is everything settled before this Sydney day, which is the
    previous day's balance at 11:59 PM. That includes completed deposits,
    withdrawals, and manual bank transfers dated before this day. Closing
    balance is the opening balance plus this day's deposits, withdrawals, and
    transfers. The next day's opening balance is therefore this closing
    balance. A chosen group or brand counts only those completed deposits and
    withdrawals. Pending, complete, and cash columns stay at 0.00.
    """
    brand, grouped, missing = _ledger_scope(group_name, brand_name)
    if missing:
        return {"date": day.isoformat(), "rows": []}
    return {"date": day.isoformat(), "rows": _ledger_rows(day, brand, grouped)}


def update_bank_ledger(
    day: date,
    bank_name: str,
    account_name: str,
    *,
    status: str | None = None,
    limit: Decimal | None = None,
    set_limit: bool = False,
    brand_name: str = "All",
    group_name: str = "All",
) -> dict:
    bank_name = bank_name.strip()
    account_name = account_name.strip()
    brand, grouped, missing = _ledger_scope(group_name, brand_name)
    if missing:
        raise LookupError("That brand was not found.")
    if status is not None and status not in LEDGER_STATUSES:
        raise ValueError("Choose a status from the list.")
    if not _ledger_account_exists(bank_name, account_name):
        raise LookupError("That bank account was not found.")
    setting, _created = BankLedgerSetting.objects.get_or_create(
        bank_name=bank_name,
        account_name=account_name,
    )
    changed: list[str] = []
    if status is not None and setting.status != status:
        setting.status = status
        changed.append("status")
    if set_limit and setting.limit_amount != limit:
        setting.limit_amount = limit
        changed.append("limit_amount")
    if changed:
        setting.save(update_fields=changed)
    row = next(
        (
            item
            for item in _ledger_rows(day, brand, grouped)
            if item["bank_name"] == bank_name and item["account_name"] == account_name
        ),
        None,
    )
    if row is None:
        raise LookupError("That bank account was not found.")
    return row


def _ledger_scope(group_name: str, brand_name: str) -> tuple[Brand | None, list[Brand] | None, bool]:
    """Resolve the sheet's group and brand.

    The brand is set when one brand is selected. The list is set when a group
    is selected and the brand is All. Both are empty when every brand is in
    scope. The last value is true when the group or brand is unknown.
    """
    group_name = (group_name or "All").strip() or "All"
    brand_name = (brand_name or "All").strip() or "All"
    known = {choice for choice, _label in Brand.GROUPS}
    if group_name != "All" and group_name not in known:
        return None, None, True
    if brand_name != "All":
        brand, missing = _ledger_brand(brand_name)
        if missing or brand is None:
            return None, None, True
        if group_name != "All" and brand.group != group_name:
            return None, None, True
        return brand, None, False
    if group_name == "All":
        return None, None, False
    grouped = list(Brand.objects.filter(is_active=True, group=group_name).order_by("sort_order", "name"))
    return None, grouped, False


def _ledger_brand(brand_name: str) -> tuple[Brand | None, bool]:
    """None means every brand. The second value is true when the name is unknown."""
    name = (brand_name or "All").strip() or "All"
    if name == "All":
        return None, False
    brand = Brand.objects.filter(is_active=True, name=name).first()
    if brand is None:
        return None, True
    return brand, False


def _ledger_account_exists(
    bank_name: str,
    account_name: str,
    brand: Brand | None = None,
    grouped: list[Brand] | None = None,
) -> bool:
    rows = Transaction.objects.filter(
        status="COMPLETED",
        type__in=("DEPOSIT", "WITHDRAW"),
        bank_name=bank_name,
        bank_account_name=account_name,
    )
    if brand is not None:
        rows = rows.filter(brand=brand)
    elif grouped is not None:
        rows = rows.filter(brand__in=grouped)
    return rows.exists()


def _ledger_rows(day: date, brand: Brand | None = None, grouped: list[Brand] | None = None) -> list[dict]:
    start, end = _sydney_bounds(day)
    zero = Decimal("0.00")
    base = (
        Transaction.objects.filter(status="COMPLETED", type__in=("DEPOSIT", "WITHDRAW"))
        .exclude(bank_name="")
        .exclude(bank_account_name="")
        .annotate(settled_at=Coalesce("processed_at", "created_at"))
        .filter(settled_at__lt=end)
    )
    if brand is not None:
        base = base.filter(brand=brand)
    elif grouped is not None:
        base = base.filter(brand__in=grouped)
    prior = _ledger_groups(base.filter(settled_at__lt=start))
    current = _ledger_groups(base.filter(settled_at__gte=start))
    settings = {
        (item.bank_name, item.account_name): item
        for item in BankLedgerSetting.objects.all()
    }
    active_keys = _active_bank_keys(brand, grouped)
    moves = _transfer_maps(day)
    keys = set(prior) | set(current) | _transfer_keys_for_scope(day, brand, grouped, set(prior) | set(current))
    rows = []
    for key in keys:
        bank_name, account_name = key
        before = prior.get(key)
        today = current.get(key)
        deposits = today["deposits"] if today else zero
        withdrawals = today["withdrawals"] if today else zero
        deposit_count = (before["deposit_count"] if before else 0) + (today["deposit_count"] if today else 0)
        withdraw_count = (before["withdraw_count"] if before else 0) + (today["withdraw_count"] if today else 0)
        setting = settings.get(key)
        chosen = setting.status if setting and setting.status in LEDGER_STATUSES else ""
        limit_amount = setting.limit_amount if setting else None
        transfer = _moves_for(moves, key)
        txn_opening = (before["deposits"] + before["withdrawals"]) if before else zero
        opening = txn_opening + transfer["prior_in"] - transfer["prior_out"]
        rows.append(
            {
                "bank_name": bank_name,
                "account_name": account_name,
                "activity": "Active" if _bank_key(bank_name, account_name) in active_keys else "Inactive",
                "status": chosen or _ledger_status(deposit_count, withdraw_count),
                "opening": _money_text(opening),
                "closing": _money_text(opening + deposits + withdrawals + transfer["day_in"] - transfer["day_out"]),
                "limit": _money_text(limit_amount) if limit_amount is not None else None,
                "deposit": _money_text(deposits),
                "withdraw": _money_text(withdrawals),
                **_LEDGER_ZERO_COLUMNS,
                "transfer_in": _money_text(transfer["day_in"]),
                "transfer_out": _money_text(-transfer["day_out"] if transfer["day_out"] else zero),
            }
        )
    rows.sort(key=lambda item: (item["bank_name"].casefold(), item["account_name"].casefold()))
    return rows


def _ledger_groups(queryset) -> dict[tuple[str, str], dict]:
    zero = Decimal("0.00")
    grouped = queryset.values("bank_name", "bank_account_name").annotate(
        deposits=Coalesce(Sum("amount", filter=Q(type="DEPOSIT")), zero, output_field=_MONEY_FIELD),
        withdrawals=Coalesce(Sum("amount", filter=Q(type="WITHDRAW")), zero, output_field=_MONEY_FIELD),
        deposit_count=Count("id", filter=Q(type="DEPOSIT")),
        withdraw_count=Count("id", filter=Q(type="WITHDRAW")),
    )
    return {
        (row["bank_name"], row["bank_account_name"]): row
        for row in grouped
    }


def bank_ledger_day(
    day: date,
    bank_name: str,
    account_name: str,
    brand_name: str = "All",
    group_name: str = "All",
) -> dict:
    """One bank account for one Sydney day: the sheet figures and that day's transactions.

    The figures use the same opening, closing, deposit, withdrawal, and transfer
    rules as the balance sheet. Transactions are the completed deposits and
    withdrawals that settled on that day for this bank and account name. A
    chosen brand counts only that brand.
    """
    bank_name = bank_name.strip()
    account_name = account_name.strip()
    brand, grouped, missing = _ledger_scope(group_name, brand_name)
    if missing:
        raise LookupError("That brand was not found.")
    if not _ledger_account_exists(bank_name, account_name, brand, grouped):
        raise LookupError("That bank account was not found.")
    start, end = _sydney_bounds(day)
    base = _ledger_account_queryset(bank_name, account_name, brand, grouped)
    prior = _ledger_totals(base.filter(settled_at__lt=start))
    current = _ledger_totals(base.filter(settled_at__gte=start, settled_at__lt=end))
    row = _ledger_account_payload(bank_name, account_name, prior, current, _account_moves(bank_name, account_name, day))
    row["activity"] = (
        "Active" if _bank_key(bank_name, account_name) in _active_bank_keys(brand, grouped) else "Inactive"
    )
    transactions = []
    settled_rows = (
        base.filter(settled_at__gte=start, settled_at__lt=end)
        .select_related("brand")
        .order_by("-settled_at", "-external_id")
    )
    for item in settled_rows:
        payload = item.display()
        payload["detail"] = item.detail or ""
        payload["time"] = _clock(item.processed_at or item.created_at)
        transactions.append(payload)
    return {"date": day.isoformat(), "row": row, "transactions": transactions}


def _ledger_account_queryset(
    bank_name: str,
    account_name: str,
    brand: Brand | None = None,
    grouped: list[Brand] | None = None,
):
    rows = Transaction.objects.filter(
        status="COMPLETED",
        type__in=("DEPOSIT", "WITHDRAW"),
        bank_name=bank_name,
        bank_account_name=account_name,
    )
    if brand is not None:
        rows = rows.filter(brand=brand)
    elif grouped is not None:
        rows = rows.filter(brand__in=grouped)
    return rows.annotate(settled_at=Coalesce("processed_at", "created_at"))


def _ledger_totals(queryset) -> dict:
    zero = Decimal("0.00")
    return queryset.aggregate(
        deposits=Coalesce(Sum("amount", filter=Q(type="DEPOSIT")), zero, output_field=_MONEY_FIELD),
        withdrawals=Coalesce(Sum("amount", filter=Q(type="WITHDRAW")), zero, output_field=_MONEY_FIELD),
        deposit_count=Count("id", filter=Q(type="DEPOSIT")),
        withdraw_count=Count("id", filter=Q(type="WITHDRAW")),
    )


def _ledger_account_payload(bank_name: str, account_name: str, prior: dict, current: dict, moves: dict | None = None) -> dict:
    zero = Decimal("0.00")
    moves = moves or {"prior_in": zero, "prior_out": zero, "day_in": zero, "day_out": zero}
    txn_opening = (prior["deposits"] or zero) + (prior["withdrawals"] or zero)
    opening = txn_opening + (moves["prior_in"] or zero) - (moves["prior_out"] or zero)
    deposits = current["deposits"] or zero
    withdrawals = current["withdrawals"] or zero
    day_in = moves["day_in"] or zero
    day_out = moves["day_out"] or zero
    deposit_count = int(prior["deposit_count"] or 0) + int(current["deposit_count"] or 0)
    withdraw_count = int(prior["withdraw_count"] or 0) + int(current["withdraw_count"] or 0)
    setting = BankLedgerSetting.objects.filter(bank_name=bank_name, account_name=account_name).first()
    chosen = setting.status if setting and setting.status in LEDGER_STATUSES else ""
    limit_amount = setting.limit_amount if setting else None
    return {
        "bank_name": bank_name,
        "account_name": account_name,
        "status": chosen or _ledger_status(deposit_count, withdraw_count),
        "opening": _money_text(opening),
        "closing": _money_text(opening + deposits + withdrawals + day_in - day_out),
        "limit": _money_text(limit_amount) if limit_amount is not None else None,
        "deposit": _money_text(deposits),
        "withdraw": _money_text(withdrawals),
        **_LEDGER_ZERO_COLUMNS,
        "transfer_in": _money_text(day_in),
        "transfer_out": _money_text(-day_out if day_out else zero),
    }


def _ledger_status(deposit_count: int, withdraw_count: int) -> str:
    if deposit_count and withdraw_count:
        return "Both"
    if deposit_count:
        return "Deposit only"
    if withdraw_count:
        return "Withdraw only"
    return "Inactive"


def _sum_transfer_side(queryset, bank_field: str, account_field: str) -> dict[tuple[str, str], Decimal]:
    zero = Decimal("0.00")
    grouped = queryset.values(bank_field, account_field).annotate(
        total=Coalesce(Sum("amount"), zero, output_field=_MONEY_FIELD),
    )
    return {
        (row[bank_field], row[account_field]): row["total"] or zero
        for row in grouped
    }


def _transfer_maps(day: date) -> dict[str, dict[tuple[str, str], Decimal]]:
    """Transfer totals for one Sydney day and for every earlier day."""
    prior = BankTransfer.objects.filter(transfer_date__lt=day)
    current = BankTransfer.objects.filter(transfer_date=day)
    return {
        "prior_in": _sum_transfer_side(prior, "to_bank_name", "to_account_name"),
        "prior_out": _sum_transfer_side(prior, "from_bank_name", "from_account_name"),
        "day_in": _sum_transfer_side(current, "to_bank_name", "to_account_name"),
        "day_out": _sum_transfer_side(current, "from_bank_name", "from_account_name"),
    }


def _moves_for(moves: dict, key: tuple[str, str]) -> dict[str, Decimal]:
    zero = Decimal("0.00")
    return {
        "prior_in": moves["prior_in"].get(key, zero),
        "prior_out": moves["prior_out"].get(key, zero),
        "day_in": moves["day_in"].get(key, zero),
        "day_out": moves["day_out"].get(key, zero),
    }


def _account_moves(bank_name: str, account_name: str, day: date) -> dict[str, Decimal]:
    return _moves_for(_transfer_maps(day), (bank_name, account_name))


def _transfer_keys_for_scope(day: date, brand: Brand | None, grouped: list[Brand] | None, already: set) -> set[tuple[str, str]]:
    """Accounts with a transfer on or before this day that the sheet should still list."""
    keys = set()
    for item in BankTransfer.objects.filter(transfer_date__lte=day).values(
        "from_bank_name", "from_account_name", "to_bank_name", "to_account_name"
    ):
        keys.add((item["from_bank_name"], item["from_account_name"]))
        keys.add((item["to_bank_name"], item["to_account_name"]))
    extra = keys - already
    if brand is None and grouped is None:
        return extra
    return {key for key in extra if _ledger_account_exists(key[0], key[1], brand, grouped)}


def bank_transfer_accounts() -> list[dict]:
    pairs = (
        Transaction.objects.filter(status="COMPLETED", type__in=("DEPOSIT", "WITHDRAW"))
        .exclude(bank_name="")
        .exclude(bank_account_name="")
        .values_list("bank_name", "bank_account_name")
        .distinct()
    )
    rows = [{"bank_name": bank, "account_name": account} for bank, account in pairs]
    rows.sort(key=lambda item: (item["bank_name"].casefold(), item["account_name"].casefold()))
    return rows


def list_bank_transfers(day: date) -> dict:
    rows = (
        BankTransfer.objects.filter(transfer_date=day)
        .select_related("created_by")
        .order_by("-created_at", "-id")
    )
    return {"date": day.isoformat(), "rows": [_transfer_payload(item) for item in rows]}


def create_bank_transfer(
    day: date,
    from_bank_name: str,
    from_account_name: str,
    to_bank_name: str,
    to_account_name: str,
    amount: Decimal,
    created_by=None,
    remarks="",
) -> dict:
    from_bank_name = from_bank_name.strip()
    from_account_name = from_account_name.strip()
    to_bank_name = to_bank_name.strip()
    to_account_name = to_account_name.strip()
    remarks = str(remarks or "").strip()
    if len(remarks) > 500:
        raise ValueError("Remarks must be 500 characters or fewer.")
    if not from_bank_name or not from_account_name or not to_bank_name or not to_account_name:
        raise ValueError("Choose the bank the money leaves and the bank it arrives in.")
    if (from_bank_name, from_account_name) == (to_bank_name, to_account_name):
        raise ValueError("Choose two different bank accounts.")
    if not _ledger_account_exists(from_bank_name, from_account_name):
        raise LookupError("The bank sending the money is not in the bank list.")
    if not _ledger_account_exists(to_bank_name, to_account_name):
        raise LookupError("The bank receiving the money is not in the bank list.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Use at most two decimal places.")
    amount = amount.quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Enter an amount greater than zero.")
    saved = BankTransfer.objects.create(
        transfer_date=day,
        created_on=sydney_today(),
        from_bank_name=from_bank_name,
        from_account_name=from_account_name,
        to_bank_name=to_bank_name,
        to_account_name=to_account_name,
        amount=amount,
        remarks=remarks,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
    )
    return _transfer_payload(saved)


def _transfer_payload(item: BankTransfer) -> dict:
    user = item.created_by
    return {
        "id": item.pk,
        "transfer_date": item.transfer_date.isoformat(),
        "created_on": item.created_on.isoformat(),
        "from_bank_name": item.from_bank_name,
        "from_account_name": item.from_account_name,
        "to_bank_name": item.to_bank_name,
        "to_account_name": item.to_account_name,
        "amount": _money_text(item.amount),
        "remarks": item.remarks,
        "transfer_time": _transfer_clock(item.created_at),
        "username": user.username if user is not None else "",
    }


def _transfer_clock(value) -> str:
    """Sydney clock time for the moment this transfer row was entered."""
    if value is None:
        return ""
    local = value.astimezone(SYDNEY) if timezone.is_aware(value) else value.replace(tzinfo=SYDNEY)
    return local.strftime("%H:%M:%S")


def bank_accounts(day: date, brand_name: str, bank_name: str) -> dict:
    """Account names and completed balances for one game and one bank.

    A bank name does not share the same accounts on every brand, so both
    filters are required before any account is returned. The date window
    matches the dashboard. This only reads stored rows.
    """
    brand_name = brand_name.strip()
    bank_name = bank_name.strip()
    result = {
        "date": day.isoformat(),
        "brand": brand_name,
        "bank_name": "",
        "banks": [],
        "accounts": [],
        "balance": "0.00",
        "deposits": "0.00",
        "withdrawals": "0.00",
        "count": 0,
        "unassigned": {"count": 0, "balance": "0.00"},
    }
    brand = Brand.objects.filter(is_active=True, name=brand_name).first()
    if brand is None:
        return result

    start, end = _sydney_bounds(day)
    completed = Transaction.objects.filter(
        brand=brand,
        created_at__gte=start,
        created_at__lt=end,
        status="COMPLETED",
        type__in=("DEPOSIT", "WITHDRAW"),
    )
    named = completed.exclude(bank_name="").exclude(bank_account_name="")
    banks = sorted(set(named.values_list("bank_name", flat=True)), key=str.casefold)
    result["banks"] = banks
    if bank_name not in banks:
        return result

    result["bank_name"] = bank_name
    zero = Decimal("0.00")
    grouped = named.filter(bank_name=bank_name).values("bank_account_name").annotate(
        balance=Coalesce(Sum("amount"), zero),
        deposits=Coalesce(Sum("amount", filter=Q(type="DEPOSIT")), zero),
        withdrawals=Coalesce(Sum("amount", filter=Q(type="WITHDRAW")), zero),
        count=Count("id"),
    )
    balance = deposits = withdrawals = zero
    count = 0
    accounts = []
    for row in sorted(grouped, key=lambda item: str(item["bank_account_name"]).casefold()):
        row_balance = row["balance"]
        row_deposits = row["deposits"]
        row_withdrawals = row["withdrawals"]
        row_count = int(row["count"])
        balance += row_balance
        deposits += row_deposits
        withdrawals += row_withdrawals
        count += row_count
        accounts.append(
            {
                "name": row["bank_account_name"],
                "balance": _money_text(row_balance),
                "deposits": _money_text(row_deposits),
                "withdrawals": _money_text(row_withdrawals),
                "count": row_count,
            }
        )
    missing = completed.filter(bank_name=bank_name, bank_account_name="").aggregate(
        balance=Coalesce(Sum("amount"), zero),
        count=Count("id"),
    )
    result.update(
        {
            "accounts": accounts,
            "balance": _money_text(balance),
            "deposits": _money_text(deposits),
            "withdrawals": _money_text(withdrawals),
            "count": count,
            "unassigned": {
                "count": int(missing["count"] or 0),
                "balance": _money_text(missing["balance"]),
            },
        }
    )
    return result


_DETAIL_LABELS = {
    "id": "ID",
    "type": "Type",
    "status": "Status",
    "cash": "Amount",
    "createdDateTime": "Created (Sydney)",
    "processedDateTime": "Processed (Sydney)",
    "endDateTime": "Ended (Sydney)",
    "bankId": "Bank ID",
    "canHandle": "Can handle",
    "merchantId": "Merchant ID",
    "adminId": "Admin ID",
    "amount": "Amount",
    "bank": "Bank",
    "method": "Method",
    "datetime": "Date time",
    "slip": "Slip",
    "bankRemark": "Bank remark",
    "gateway": "Gateway",
    "MBOStaffName": "Staff",
    "bankAccountName": "Account name",
    "bankAccountNumber": "Account number",
    "bankBSB": "BSB",
    "payID": "PayID",
    "bankLock": "Bank lock",
    "walletId": "Wallet ID",
    "forfeited": "Forfeited",
    "remarks": "Remarks",
    "angpao": "Angpao",
    "promotionId": "Promotion ID",
    "username": "Username",
    "originalName": "Name",
    "mobile": "Mobile",
    "last_dep_datetime": "Last deposit",
    "name": "Name",
}
_SYDNEY_KEYS = {"createdDateTime", "processedDateTime", "endDateTime"}
_MONEY_KEYS = {"cash", "amount"}
_FLAG_KEYS = {"canHandle", "bankLock"}
_NESTED_KEYS = {"user", "details", "promotion", "admin", "bank"}


def transaction_record(brand_name: str, external_id: str) -> tuple[dict | None, str]:
    """Live brand-API record for one stored transaction.

    The id is taken from the clicked row and checked against that brand.
    Only the API object with that same id is returned. Nothing is written.
    """
    brand_name = brand_name.strip()
    external_id = external_id.strip()
    brand = Brand.objects.filter(is_active=True, name=brand_name).first()
    if brand is None or not external_id:
        return None, "That transaction was not found."
    if not Transaction.objects.filter(brand=brand, external_id=external_id).exists():
        return None, "That transaction was not found."
    if not brand.token or not brand.merchant_id:
        return None, f"{brand.name} has no API access configured."

    url = brand.domain.rstrip("/") + "/api/v1/index.php"
    form = {
        "module": "/transactions/getAllTransactions",
        "accessId": brand.access_id,
        "accessToken": brand.token,
        "merchantId": brand.merchant_id,
        "pageIndex": "0",
        "pageSize": "5",
        "transactionId": external_id,
        "includeAdmin": "1",
    }
    try:
        body = _post(url, form).json()
    except requests.RequestException:
        return None, "The brand API could not be reached."
    except ValueError:
        return None, "The brand API did not return JSON."
    if str(body.get("status") or "") != "SUCCESS":
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        message = str(data.get("message") or "") or "The brand API refused the request."
        return None, message

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    rows = data.get("transactions") if isinstance(data.get("transactions"), list) else []
    match = next((row for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip() == external_id), None)
    if match is None:
        return None, "The brand API did not return this transaction."
    return _present_transaction(brand.name, external_id, match), ""


def _present_transaction(brand_name: str, external_id: str, raw: dict) -> dict:
    details = _json_dict(raw.get("details"))
    user = raw.get("user") if isinstance(raw.get("user"), dict) else _json_dict(raw.get("user"))
    player_bank = _json_dict(user.get("bank"))
    promotion = raw.get("promotion") if isinstance(raw.get("promotion"), dict) else _json_dict(raw.get("promotion"))
    admin = raw.get("admin") if isinstance(raw.get("admin"), dict) else _json_dict(raw.get("admin"))
    tags = [part for part in (_clean_label(item) for item in _TAG_RE.findall(str(user.get("name") or ""))) if part]

    transaction_fields = _fields(
        raw,
        ("id", "type", "status", "cash", "createdDateTime", "processedDateTime", "endDateTime", "bankId", "canHandle", "merchantId", "adminId"),
    )
    transaction_fields.insert(0, {"label": "Game", "value": brand_name, "href": ""})
    sections = [{"title": "Transaction", "fields": transaction_fields}]
    detail_fields = _fields(
        details,
        (
            "amount",
            "bank",
            "method",
            "gateway",
            "bankRemark",
            "slip",
            "datetime",
            "MBOStaffName",
            "bankAccountName",
            "bankAccountNumber",
            "bankBSB",
            "payID",
            "bankLock",
            "forfeited",
            "walletId",
            "remarks",
            "angpao",
            "promotionId",
        ),
    )
    if detail_fields:
        sections.append({"title": "Payment details", "fields": detail_fields})
    player = dict(user)
    player.pop("bank", None)
    player.pop("name", None)
    player_fields = _fields(player, ("username", "originalName", "mobile", "id", "last_dep_datetime"))
    if tags:
        player_fields.append({"label": "Tags", "value": ", ".join(tags), "href": ""})
    if player_fields:
        sections.append({"title": "Player", "fields": player_fields})
    bank_fields = _fields(player_bank, ("bank", "bankAccountName", "bankAccountNumber", "bankBSB", "payID", "bankLock"))
    if bank_fields:
        sections.append({"title": "Player bank", "fields": bank_fields})
    promotion_fields = _fields(promotion, ("name", "id"))
    if promotion_fields:
        sections.append({"title": "Promotion", "fields": promotion_fields})
    admin_fields = _fields(admin, ("name", "username", "id"))
    if admin_fields:
        sections.append({"title": "Processed by", "fields": admin_fields})

    return {
        "brand": brand_name,
        "id": external_id,
        "type": str(raw.get("type") or ""),
        "status": str(raw.get("status") or ""),
        "sections": sections,
    }


def _json_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip()[:1] in "{[":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _fields(data: dict, order: tuple[str, ...]) -> list[dict]:
    fields = []
    seen: set[str] = set()
    for key in (*order, *(key for key in data if key not in order)):
        if key in seen or key in _NESTED_KEYS:
            continue
        seen.add(key)
        shown = _format_field(key, data.get(key))
        if shown is None:
            continue
        fields.append({"label": _DETAIL_LABELS.get(key, _label(key)), **shown})
    return fields


def _format_field(key: str, value: object) -> dict | None:
    if isinstance(value, (dict, list)):
        if not value:
            return None
        text = json.dumps(value, ensure_ascii=False, default=str)
    elif key in _FLAG_KEYS and str(value) in {"0", "1"}:
        text = "Yes" if str(value) == "1" else "No"
    elif key in _MONEY_KEYS and value not in (None, ""):
        try:
            text = f"{Decimal(str(value)):.2f}"
        except (InvalidOperation, ValueError):
            text = _plain(value)
    elif key in _SYDNEY_KEYS:
        parsed = _parse_dt(value)
        text = _clock(parsed) if parsed is not None else _plain(value)
    else:
        text = _plain(value)
    if not text or text.lower() in {"none", "null"}:
        return None
    href = text if text.startswith(("http://", "https://")) else ""
    return {"value": text, "href": href}


def _plain(value: object) -> str:
    text = str(value if value is not None else "")
    if "<" in text and ">" in text:
        text = _HTML_RE.sub("", text)
    return _clean_label(text)


def _label(key: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(key)).replace("_", " ")
    return spaced[:1].upper() + spaced[1:]


def _read_day(day: date) -> tuple[list[dict], list[dict]]:
    """Rows whose created time falls on this Sydney calendar day. Stored rows are not rewritten."""
    start, end = _sydney_bounds(day)
    queryset = (
        Transaction.objects.select_related("brand")
        .filter(created_at__gte=start, created_at__lt=end)
        .order_by("-created_at", "-external_id")
    )
    rows = [item.display() for item in queryset]
    rows.sort(key=lambda row: row["status"] != "PENDING")
    syncs = {item.brand_id: item for item in BrandSync.objects.select_related("brand").filter(day=day)}
    brands = []
    for brand in Brand.objects.filter(is_active=True).order_by("sort_order", "name"):
        sync = syncs.get(brand.id)
        updated = sync.updated_at if sync else None
        brands.append(
            {
                "name": brand.name,
                "sort_order": brand.sort_order,
                "message": sync.message if sync else "",
                "row_count": sync.row_count if sync else 0,
                "updated_at": updated.isoformat() if updated else None,
            }
        )
    return rows, brands
