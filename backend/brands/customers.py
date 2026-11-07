"""Player register from each brand, plus who played and who joined on a Sydney day.

/users/getAllUsers is oldest-first and has no date filter. New accounts sit on the
last pages. A background pass copies the full register. The page for one day
reads the pages that cover that registration date, then counts deposits and
withdrawals from the transactions already stored for that day.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal

import requests
from django.db import close_old_connections, transaction
from django.db.models import Count, Q

from brands.models import SYDNEY, Brand, Customer, CustomerSync, Transaction, _clock, sydney_today
from brands.services import _money, _parse_dt, _post

PAGE_SIZE = 500
_HTML_RE = re.compile(r"<[^>]+>")
_started = False
_guard = threading.Lock()
_locks_guard = threading.Lock()
_brand_locks: dict[int, threading.Lock] = {}
_ready: dict[tuple[int, str], float] = {}
_fail_until: dict[int, float] = {}
_TODAY_TTL = 30.0
_PAST_TTL = 6 * 60 * 60.0
_WALK_LIMIT = 20


def start_customer_sync() -> None:
    global _started
    with _guard:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="customer-sync", daemon=True).start()


def customer_board(day: date, brand_name: str, query: str, page: int) -> dict:
    """Registered customers, who played that day, and who joined that day."""
    brands, missing = _scoped_brands(brand_name)
    if missing:
        empty = _empty_registered(page)
        return {
            "date": day.isoformat(),
            "brand": brand_name,
            "registered": empty,
            "played": {"count": 0, "rows": []},
            "joined": {"count": 0, "rows": []},
            "errors": ["That brand was not found."],
        }
    errors = ensure_joined(brands, day)
    registered = _registered(brands, query, page)
    played = _played(brands, day)
    joined = _joined(brands, day)
    return {
        "date": day.isoformat(),
        "brand": brand_name if brand_name else "All",
        "registered": registered,
        "played": played,
        "joined": joined,
        "errors": errors,
    }


def ensure_joined(brands: list[Brand], day: date) -> list[str]:
    if not brands:
        return []

    def work(brand: Brand) -> tuple[str, str]:
        close_old_connections()
        try:
            return brand.name, _ensure_brand_day(brand, day)
        except Exception:
            return brand.name, "The customer list could not be read."
        finally:
            close_old_connections()

    errors: list[str] = []
    workers = min(4, len(brands))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="customer-day") as pool:
        for name, error in pool.map(work, brands):
            if error:
                errors.append(f"{name}: {error}")
    return errors


def _ensure_brand_day(brand: Brand, day: date) -> str:
    key = (brand.pk, day.isoformat())
    now = time.monotonic()
    ttl = _TODAY_TTL if day >= sydney_today() else _PAST_TTL
    with _guard:
        seen = _ready.get(key)
        if seen is not None and now - seen < ttl:
            return ""
    if day < sydney_today() and _backfill_done(brand):
        with _guard:
            _ready[key] = time.monotonic()
        return ""
    with _lock_for(brand.pk):
        error = _load_day(brand, day)
    if not error:
        with _guard:
            _ready[key] = time.monotonic()
    return error


def _backfill_done(brand: Brand) -> bool:
    sync = CustomerSync.objects.filter(brand=brand).only("next_page", "total_pages").first()
    return bool(sync and sync.total_pages and sync.next_page >= sync.total_pages)


def _load_day(brand: Brand, day: date) -> str:
    start, end = _bounds(day)
    sync = CustomerSync.objects.filter(brand=brand).only("total_pages").first()
    total = sync.total_pages if sync and sync.total_pages else 0
    if total <= 0:
        batch, total, error = _fetch_page(brand, 0)
        if error:
            return error
        if total <= 0:
            return ""
        _upsert(brand, batch)
        _note_total(brand, total)
        if total == 1:
            return ""
    last = total - 1
    batch, new_total, error = _fetch_page(brand, last)
    if error:
        return error
    if new_total and new_total != total:
        total = new_total
        last = max(total - 1, 0)
        batch, new_total, error = _fetch_page(brand, last)
        if error:
            return error
        if new_total:
            total = new_total
            last = max(total - 1, 0)
    _upsert(brand, batch)
    _note_total(brand, total)
    first_at, last_at = _span(batch)
    if last_at is not None and last_at < start:
        return ""
    if first_at is not None and first_at >= end:
        return _binary_fill(brand, start, end, last)
    return _walk_back(brand, start, last - 1)


def _binary_fill(brand: Brand, start: datetime, end: datetime, last_page: int) -> str:
    low = 0
    high = last_page
    first = last_page + 1
    while low <= high:
        mid = (low + high) // 2
        batch, _total, error = _fetch_page(brand, mid)
        if error:
            return error
        _upsert(brand, batch)
        _first, last_at = _span(batch)
        if last_at is None or last_at < start:
            low = mid + 1
        else:
            first = mid
            high = mid - 1
    if first > last_page:
        return ""
    page = first
    steps = 0
    while page <= last_page and steps < _WALK_LIMIT:
        batch, _total, error = _fetch_page(brand, page)
        if error:
            return error
        _upsert(brand, batch)
        first_at, _last = _span(batch)
        if first_at is not None and first_at >= end:
            break
        page += 1
        steps += 1
    return ""


def _walk_back(brand: Brand, start: datetime, page: int) -> str:
    steps = 0
    while page >= 0 and steps < _WALK_LIMIT:
        batch, _total, error = _fetch_page(brand, page)
        if error:
            return error
        _upsert(brand, batch)
        _first, last_at = _span(batch)
        if last_at is not None and last_at < start:
            break
        page -= 1
        steps += 1
    return ""


def _loop() -> None:
    while True:
        busy = False
        try:
            brands = list(Brand.objects.filter(is_active=True).exclude(token="").exclude(merchant_id=""))
            close_old_connections()
            if brands:
                def step(brand: Brand) -> bool:
                    close_old_connections()
                    try:
                        return _sync_one(brand)
                    except Exception:
                        return True
                    finally:
                        close_old_connections()

                workers = min(4, len(brands))
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="customer-backfill") as pool:
                    busy = any(pool.map(step, brands))
        except Exception:
            busy = True
        finally:
            close_old_connections()
        time.sleep(0.4 if busy else 20)


def _sync_one(brand: Brand) -> bool:
    """Copy one register page. Known brands are refreshed newest-first. Returns True while pages remain."""
    now = time.monotonic()
    if _fail_until.get(brand.pk, 0) > now:
        return False
    with _lock_for(brand.pk):
        sync, _created = CustomerSync.objects.get_or_create(brand=brand)
        if sync.total_pages and sync.next_page >= sync.total_pages:
            return False
        page = sync.next_page
        if sync.total_pages:
            page = max(sync.total_pages - 1 - sync.next_page, 0)
        batch, total, error = _fetch_page(brand, page)
        if error:
            sync.message = error[:500]
            sync.save(update_fields=["message", "updated_at"])
            _fail_until[brand.pk] = time.monotonic() + 30
            return False
        if total <= 0 and not batch:
            sync.total_pages = max(sync.total_pages, 1)
            sync.next_page = sync.total_pages
            sync.message = ""
            sync.save(update_fields=["next_page", "total_pages", "message", "updated_at"])
            return False
        _upsert(brand, batch)
        sync.total_pages = total or sync.total_pages
        sync.next_page = sync.next_page + 1
        sync.message = ""
        sync.save(update_fields=["next_page", "total_pages", "message", "updated_at"])
        if not sync.total_pages:
            return False
        return sync.next_page < sync.total_pages


def _fetch_page(brand: Brand, page: int) -> tuple[list[dict], int, str]:
    if page < 0 or not brand.token or not brand.merchant_id:
        return [], 0, ""
    url = brand.domain.rstrip("/") + "/api/v1/index.php"
    form = {
        "module": "/users/getAllUsers",
        "accessId": brand.access_id,
        "accessToken": brand.token,
        "merchantId": brand.merchant_id,
        "pageIndex": str(page),
        "pageSize": str(PAGE_SIZE),
    }
    try:
        body = _post(url, form).json()
    except requests.RequestException:
        return [], 0, "The brand API could not be reached."
    except ValueError:
        return [], 0, "The brand API did not return JSON."
    if str(body.get("status") or "") != "SUCCESS":
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        message = str(data.get("message") or "") or "The brand API refused the request."
        return [], 0, message
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    users = data.get("users") if isinstance(data.get("users"), list) else []
    rows = [item for item in users if isinstance(item, dict)]
    try:
        total = int(data.get("totalPage") or 0)
    except (TypeError, ValueError):
        total = 0
    return rows, max(total, 0), ""


def _upsert(brand: Brand, users: list[dict]) -> None:
    prepared: list[Customer] = []
    for user in users:
        external_id = str(user.get("id") or user.get("username") or "").strip()
        if not external_id:
            continue
        name = _HTML_RE.sub("", str(user.get("name") or ""))
        name = " ".join(name.split())
        bank = _bank_fields(user.get("bank"))
        prepared.append(
            Customer(
                brand=brand,
                external_id=external_id[:64],
                username=str(user.get("username") or "")[:128],
                name=name[:255],
                mobile=str(user.get("mobile") or "")[:64],
                email=str(user.get("playerEmail") or "")[:255],
                status=str(user.get("status") or "")[:32],
                account_type=str(user.get("type") or "")[:32],
                registered_at=_parse_dt(user.get("createdDateTime")),
                visited_at=_parse_dt(user.get("visitedDateTime")),
                cash_site_at=_parse_dt(user.get("cashSiteDatetime")),
                cash=_money(user.get("cash")),
                lifetime_deposit=_money(user.get("lifetimeDeposit")),
                lifetime_deposit_count=_count(user.get("lifetimeDepositCount")),
                referrer_name=str(user.get("referrerName") or "")[:128],
                referrer_code=str(user.get("referrerCode") or "")[:64],
                tags=_tags(user),
                **bank,
            )
        )
    if not prepared:
        return
    prepared = list({item.external_id: item for item in prepared}.values())
    with transaction.atomic():
        Customer.objects.bulk_create(
            prepared,
            update_conflicts=True,
            unique_fields=["brand", "external_id"],
            update_fields=[
                "username",
                "name",
                "mobile",
                "email",
                "status",
                "account_type",
                "registered_at",
                "visited_at",
                "cash_site_at",
                "cash",
                "lifetime_deposit",
                "lifetime_deposit_count",
                "referrer_name",
                "referrer_code",
                "tags",
                "bank_name",
                "bank_account_name",
                "bank_account_number",
                "bank_bsb",
                "pay_id",
                "bank_locked",
            ],
        )


def _registered(brands: list[Brand], query: str, page: int) -> dict:
    qs = Customer.objects.filter(brand__in=brands)
    needle = query.strip()
    if needle:
        qs = qs.filter(
            Q(username__icontains=needle)
            | Q(name__icontains=needle)
            | Q(mobile__icontains=needle)
            | Q(email__icontains=needle)
            | Q(bank_name__icontains=needle)
            | Q(bank_account_name__icontains=needle)
            | Q(bank_account_number__icontains=needle)
            | Q(pay_id__icontains=needle)
            | Q(referrer_name__icontains=needle)
            | Q(referrer_code__icontains=needle)
        )
    total = qs.count()
    page_size = 50
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(page, 1), pages)
    offset = (page - 1) * page_size
    window = list(
        qs.select_related("brand").order_by("-registered_at", "brand__sort_order", "username", "id")[
            offset : offset + page_size
        ]
    )
    rows = _with_withdrawals(window)
    syncs = list(CustomerSync.objects.filter(brand__in=brands))
    loaded = Customer.objects.filter(brand__in=brands).count()
    known = [item for item in syncs if item.total_pages]
    complete = bool(brands) and len(known) == len(brands) and all(item.next_page >= item.total_pages for item in known)
    return {
        "count": total,
        "loaded": loaded,
        "complete": complete,
        "page": page,
        "pages": pages if total else 1,
        "rows": rows,
    }


def _played(brands: list[Brand], day: date) -> dict:
    people: dict[str, dict] = {}
    rows = Transaction.objects.filter(
        txn_date=day,
        brand__in=brands,
        status="COMPLETED",
        type__in=["DEPOSIT", "WITHDRAW"],
    ).values_list(
        "brand__name",
        "username",
        "player_name",
        "mobile",
        "type",
    )
    for brand_name, username, player_name, mobile, kind in rows.iterator(chunk_size=2000):
        username = (username or "").strip()
        key = username.casefold() if username else f"{brand_name}|{player_name}|{mobile}"
        item = people.get(key)
        if item is None:
            item = {
                "username": username,
                "name": (player_name or "").strip(),
                "mobile": (mobile or "").strip(),
                "brands": set(),
                "deposits": 0,
                "withdrawals": 0,
            }
            people[key] = item
        if player_name and not item["name"]:
            item["name"] = str(player_name).strip()
        if mobile and not item["mobile"]:
            item["mobile"] = str(mobile).strip()
        if username and not item["username"]:
            item["username"] = username
        item["brands"].add(brand_name)
        if kind == "DEPOSIT":
            item["deposits"] += 1
        elif kind == "WITHDRAW":
            item["withdrawals"] += 1
    listed = []
    for item in people.values():
        names = sorted(name for name in item["brands"] if name)
        listed.append(
            {
                "username": item["username"],
                "name": item["name"],
                "mobile": item["mobile"],
                "games": len(names),
                "brands": names,
                "deposits": item["deposits"],
                "withdrawals": item["withdrawals"],
            }
        )
    listed.sort(key=lambda row: (-row["games"], -row["deposits"], -row["withdrawals"], row["name"].casefold(), row["username"].casefold()))
    return {"count": len(listed), "rows": listed}


def _joined(brands: list[Brand], day: date) -> dict:
    start, end = _bounds(day)
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    tallies = (
        Transaction.objects.filter(
            txn_date=day,
            brand__in=brands,
            status="COMPLETED",
            type__in=["DEPOSIT", "WITHDRAW"],
        )
        .values("brand__name", "username")
        .annotate(
            deposits=Count("id", filter=Q(type="DEPOSIT")),
            withdrawals=Count("id", filter=Q(type="WITHDRAW")),
        )
    )
    for row in tallies:
        counts[(row["brand__name"], (row["username"] or "").strip().casefold())] = (
            row["deposits"],
            row["withdrawals"],
        )
    listed = []
    qs = (
        Customer.objects.filter(brand__in=brands, registered_at__gte=start, registered_at__lt=end)
        .select_related("brand")
        .order_by("-registered_at", "brand__sort_order", "username")
    )
    for item in qs:
        deposits, withdrawals = counts.get((item.brand.name, item.username.casefold()), (0, 0))
        row = _customer_row(item)
        row["deposits"] = deposits
        row["withdrawals"] = withdrawals
        listed.append(row)
    return {"count": len(listed), "rows": listed}


_WITHDRAW_TTL = 120
_recounted: set[int] = set()


def _player_completed_total(brand: Brand, user_id: str, kind: str) -> tuple[Decimal, int] | None:
    """Lifetime total for one player, excluding rejected withdrawals.

    The brand API totalAmount and totalCount still include rejected rows, so
    each transaction is counted on its own. userId is the brand player id.
    """
    if not user_id or not brand.token or not brand.merchant_id:
        return None
    url = brand.domain.rstrip("/") + "/api/v1/index.php"
    amount = Decimal("0")
    count = 0
    page = 0
    page_size = 100
    while page < 400:
        try:
            body = _post(
                url,
                {
                    "module": "/transactions/getAllTransactions",
                    "accessId": brand.access_id,
                    "accessToken": brand.token,
                    "merchantId": brand.merchant_id,
                    "pageIndex": str(page),
                    "pageSize": str(page_size),
                    "status": "COMPLETED",
                    "type": kind,
                    "sDate": "2000-01-01 00:00:00",
                    "eDate": "2099-12-31 23:59:59",
                    "userId": user_id,
                },
            ).json()
        except (requests.RequestException, ValueError):
            return None
        if str(body.get("status") or "") != "SUCCESS":
            return None
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        batch = data.get("transactions") if isinstance(data.get("transactions"), list) else []
        for raw in batch:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("status") or "").strip().upper() == "REJECTED":
                continue
            txn_type = str(raw.get("type") or "").strip().upper()
            if txn_type and txn_type != kind:
                continue
            amount += abs(_money(raw.get("cash")))
            count += 1
        try:
            total_page = max(1, int(data.get("totalPage") or 1))
        except (TypeError, ValueError):
            total_page = 1
        if not batch or page + 1 >= total_page:
            break
        page += 1
    return amount, count


def _refresh_withdrawals(customers: list[Customer]) -> None:
    def load(item: Customer) -> tuple[int, tuple[Decimal, int] | None]:
        close_old_connections()
        try:
            return item.pk, _player_completed_total(item.brand, item.external_id, "WITHDRAW")
        except Exception:
            return item.pk, None
        finally:
            close_old_connections()

    workers = min(8, len(customers))
    found: list[Customer] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lifetime-withdraw") as pool:
        for item, result in zip(customers, pool.map(load, customers)):
            customer_id, totals = result
            if customer_id != item.pk or totals is None:
                continue
            amount, count = totals
            item.lifetime_withdraw = amount
            item.lifetime_withdraw_count = count
            found.append(item)
    if not found:
        return
    from django.utils import timezone

    stamped = timezone.now()
    for item in found:
        item.withdraw_synced_at = stamped
    Customer.objects.bulk_update(
        found,
        ["lifetime_withdraw", "lifetime_withdraw_count", "withdraw_synced_at"],
    )
    _recounted.update(item.pk for item in found)


def _with_withdrawals(customers: list[Customer]) -> list[dict]:
    """Lifetime withdrawals from the transaction API, excluding rejected rows."""
    stale = []
    for item in customers:
        synced = item.withdraw_synced_at
        age = None if synced is None else time.time() - synced.timestamp()
        if item.pk not in _recounted or age is None or age > _WITHDRAW_TTL:
            stale.append(item)
    if stale:
        _refresh_withdrawals(stale)
    rows = []
    for item in customers:
        row = _customer_row(item)
        row["lifetime_withdraw"] = f"{item.lifetime_withdraw:.2f}"
        row["lifetime_withdraw_count"] = item.lifetime_withdraw_count
        rows.append(row)
    return rows


def _customer_row(item: Customer) -> dict:
    referrer = item.referrer_name
    if item.referrer_code:
        referrer = f"{referrer} ({item.referrer_code})" if referrer else item.referrer_code
    return {
        "id": item.external_id,
        "username": item.username,
        "name": item.name,
        "mobile": item.mobile,
        "email": item.email,
        "status": item.status,
        "type": item.account_type,
        "brand": item.brand.name,
        "cash": f"{item.cash:.2f}",
        "lifetime_deposit": f"{item.lifetime_deposit:.2f}",
        "lifetime_deposit_count": item.lifetime_deposit_count,
        "bank_name": item.bank_name,
        "bank_account_name": item.bank_account_name,
        "bank_account_number": item.bank_account_number,
        "bsb": item.bank_bsb,
        "pay_id": item.pay_id,
        "bank_locked": "Locked" if item.bank_locked else "",
        "referrer": referrer,
        "tags": item.tags,
        "registered": _clock(item.registered_at),
        "visited": _clock(item.visited_at),
        "cash_site": _clock(item.cash_site_at),
    }


def _scoped_brands(brand_name: str) -> tuple[list[Brand], bool]:
    qs = Brand.objects.filter(is_active=True).exclude(token="").exclude(merchant_id="").order_by("sort_order", "name")
    name = (brand_name or "All").strip() or "All"
    if name == "All":
        return list(qs), False
    brand = qs.filter(name=name).first()
    if brand is None:
        return [], True
    return [brand], False


def _empty_registered(page: int) -> dict:
    return {"count": 0, "loaded": 0, "complete": True, "page": max(page, 1), "pages": 1, "rows": []}


def _note_total(brand: Brand, total: int) -> None:
    if total <= 0:
        return
    CustomerSync.objects.get_or_create(brand=brand)
    CustomerSync.objects.filter(brand=brand, total_pages__lt=total).update(total_pages=total)


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=SYDNEY)
    return start, start + timedelta(days=1)


def _span(users: list[dict]) -> tuple[datetime | None, datetime | None]:
    times = [stamp for stamp in (_parse_dt(user.get("createdDateTime")) for user in users) if stamp is not None]
    if not times:
        return None, None
    return min(times), max(times)


def _bank_fields(raw: object) -> dict:
    parsed: dict = {}
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{"):
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                parsed = loaded
    lock = str(parsed.get("bankLock") or "").strip().lower()
    return {
        "bank_name": str(parsed.get("bank") or "")[:128],
        "bank_account_name": str(parsed.get("bankAccountName") or "")[:255],
        "bank_account_number": str(parsed.get("bankAccountNumber") or "")[:64],
        "bank_bsb": str(parsed.get("bankBSB") or "")[:32],
        "pay_id": str(parsed.get("payID") or "")[:128],
        "bank_locked": lock not in {"", "0", "false", "no"},
    }


def _tags(user: dict) -> str:
    raw = user.get("userTag")
    tag = raw.get("tag") if isinstance(raw, dict) else None
    if not isinstance(tag, dict):
        return ""
    parts = []
    for key, value in tag.items():
        text = str(value or "").strip()
        if not text:
            continue
        parts.append(f"{key}: {text}")
    return ", ".join(parts)[:255]


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _lock_for(brand_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _brand_locks.get(brand_id)
        if lock is None:
            lock = threading.Lock()
            _brand_locks[brand_id] = lock
        return lock
