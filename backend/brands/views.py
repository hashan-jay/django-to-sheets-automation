import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from brands import livecache
from brands.models import SYDNEY, Brand, sydney_today
from brands.poller import note_watch, start_poller
from brands.customers import customer_board, start_customer_sync
from brands.services import (
    bank_accounts,
    bank_ledger,
    bank_ledger_day,
    bank_transfer_accounts,
    create_bank_transfer,
    list_bank_transfers,
    load_dashboard,
    sync_day,
    transaction_record,
    update_bank_ledger,
)


class BrandListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        brands = Brand.objects.filter(is_active=True).order_by("sort_order", "name")
        return Response([{"id": brand.id, "name": brand.name, "group": brand.group} for brand in brands])


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        note_watch(day)
        start_poller()
        group_name = str(request.query_params.get("group") or "All")
        brand_name = str(request.query_params.get("brand") or "All")
        wanted_type = str(request.query_params.get("type") or "All types")
        wanted_status = str(request.query_params.get("status") or "All statuses")
        client_rev = str(request.query_params.get("rev") or "")
        if client_rev:
            current = livecache.revision(day)
            if current is not None and current == client_rev:
                return _live_response({"unchanged": True, "revision": int(current)})
        return _live_response(
            _dashboard_body(day, brand_name, wanted_type, wanted_status, load_dashboard(day), group_name)
        )


class BankAccountsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        brand_name = str(request.query_params.get("brand") or "")
        bank_name = str(request.query_params.get("bank_name") or "")
        return _live_response(bank_accounts(day, brand_name, bank_name))


class BankLedgerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        group_name = str(request.query_params.get("group") or "All")
        brand_name = str(request.query_params.get("brand") or "All")
        return _live_response(bank_ledger(day, brand_name, group_name))

    def post(self, request):
        day = _parse_day(request.data.get("date"))
        group_name = str(request.data.get("group") or "All")
        brand_name = str(request.data.get("brand") or "All")
        bank_name = str(request.data.get("bank_name") or "")
        account_name = str(request.data.get("account_name") or "")
        fields = request.data if isinstance(request.data, dict) else {}
        status = str(fields["status"]) if "status" in fields and fields.get("status") is not None else None
        set_limit = "limit" in fields
        try:
            limit = _parse_limit(fields.get("limit")) if set_limit else None
            row = update_bank_ledger(
                day,
                bank_name,
                account_name,
                status=status,
                limit=limit,
                set_limit=set_limit,
                brand_name=brand_name,
                group_name=group_name,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        return _live_response({"row": row})


class BankLedgerDayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        group_name = str(request.query_params.get("group") or "All")
        brand_name = str(request.query_params.get("brand") or "All")
        bank_name = str(request.query_params.get("bank_name") or "")
        account_name = str(request.query_params.get("account_name") or "")
        if not bank_name.strip() or not account_name.strip():
            return Response({"detail": "Choose a bank account."}, status=400)
        try:
            payload = bank_ledger_day(day, bank_name, account_name, brand_name, group_name)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        return _live_response(payload)


class BankTransferListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        return _live_response(list_bank_transfers(day))

    def post(self, request):
        fields = request.data if isinstance(request.data, dict) else {}
        day = _parse_transfer_day(fields.get("date"))
        if day is None:
            return Response({"detail": "Choose the date the transfer was done."}, status=400)
        try:
            amount = _parse_transfer_amount(fields.get("amount"))
            row = create_bank_transfer(
                day,
                str(fields.get("from_bank_name") or ""),
                str(fields.get("from_account_name") or ""),
                str(fields.get("to_bank_name") or ""),
                str(fields.get("to_account_name") or ""),
                amount,
                request.user,
                str(fields.get("remarks") or ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        return _live_response({"row": row})


class BankTransferAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _live_response({"accounts": bank_transfer_accounts()})


class CustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        note_watch(day)
        start_poller()
        start_customer_sync()
        brand_name = str(request.query_params.get("brand") or "All")
        query = str(request.query_params.get("q") or "")[:80]
        return _live_response(customer_board(day, brand_name, query, _parse_page(request.query_params.get("page"))))


class TransactionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand_name = str(request.query_params.get("brand") or "")
        external_id = str(request.query_params.get("id") or "")
        if not brand_name.strip() or not external_id.strip():
            return Response({"detail": "Choose a transaction."}, status=400)
        payload, error = transaction_record(brand_name, external_id)
        if error:
            return Response({"detail": error}, status=404)
        return _live_response(payload)


class SyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        day = _parse_day(request.data.get("date") or request.query_params.get("date"))
        note_watch(day)
        sync_day(day)
        return Response({"ok": True, "date": day.isoformat()})


def _refused_ip(errors: list[str]) -> str:
    for message in errors:
        match = re.search(r"Invalid Access IP \[([0-9.]+)\]", message)
        if match:
            return match.group(1)
    return ""


def _parse_limit(value: object) -> Decimal | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text.upper() in {"", "N/A"}:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Enter a limit amount, or leave it blank for N/A.") from exc
    if not amount.is_finite() or abs(amount) >= Decimal("1000000000000"):
        raise ValueError("Enter a limit amount, or leave it blank for N/A.")
    return amount.quantize(Decimal("0.01"))


def _parse_page(value: object) -> int:
    try:
        page = int(str(value or "1").strip())
    except ValueError:
        return 1
    return min(max(page, 1), 100000)


def _parse_day(value: object):
    text = str(value or "").strip()
    if text:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            pass
    return sydney_today()


def _parse_transfer_day(value: object):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_transfer_amount(value: object) -> Decimal:
    text = str(value or "").strip().replace(",", "")
    if not text:
        raise ValueError("Enter the amount.")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError("Enter the amount in dollars and cents.")
    return amount


def _live_response(body: dict) -> Response:
    response = Response(body)
    response["Cache-Control"] = "no-store"
    return response


def _dashboard_body(
    day,
    brand_name: str,
    wanted_type: str,
    wanted_status: str,
    packed: dict,
    group_name: str = "All",
) -> dict:
    rows = packed.get("rows") or []
    brands_meta = packed.get("brands") or []
    group_name = (group_name or "All").strip() or "All"
    if group_name != "All":
        known = {choice for choice, _label in Brand.GROUPS}
        if group_name in known:
            allowed = set(Brand.objects.filter(is_active=True, group=group_name).values_list("name", flat=True))
        else:
            allowed = set()
        if brand_name != "All" and brand_name not in allowed:
            allowed = set()
        rows = [row for row in rows if row.get("brand") in allowed]
        brands_meta = [item for item in brands_meta if item.get("name") in allowed]
    if brand_name != "All":
        scoped = [row for row in rows if row.get("brand") == brand_name]
        meta = [item for item in brands_meta if item.get("name") == brand_name]
    else:
        scoped = list(rows)
        meta = list(brands_meta)
    visible = scoped
    if wanted_type != "All types":
        visible = [row for row in visible if row.get("type") == wanted_type]
    if wanted_status != "All statuses":
        visible = [row for row in visible if _matches_status(row, wanted_status)]

    total_rows = len(scoped)
    errors = [str(item.get("message") or "") for item in meta if item.get("message")]
    synced_at = _latest_sync(meta)
    stamp = synced_at.astimezone(SYDNEY).strftime("%H:%M:%S") if synced_at else ""
    refused_ip = _refused_ip(errors)
    if refused_ip:
        status_line = (
            f"{stamp}  {total_rows} saved rows. "
            f"The brand APIs refused this computer's address {refused_ip}."
        ).strip()
    elif errors and total_rows == 0:
        status_line = (stamp + "  " + " ".join(errors[:3])).strip()
    elif errors:
        status_line = f"{stamp}  {total_rows} API rows. " + " ".join(errors[:2])
    elif synced_at:
        status_line = f"Live {stamp}  ·  {total_rows} API rows."
    else:
        status_line = "Connecting to the brand APIs."

    if brand_name == "All":
        order = {item.get("name"): item.get("sort_order") or 0 for item in brands_meta}
        names = sorted({row.get("brand") for row in scoped if row.get("brand")}, key=lambda name: (order.get(name, 0), name))
    else:
        names = [brand_name]
    totals: dict[str, int] = {}
    pending: dict[str, int] = {}
    for row in scoped:
        name = row.get("brand") or ""
        totals[name] = totals.get(name, 0) + 1
        if row.get("status") == "PENDING":
            pending[name] = pending.get(name, 0) + 1
    if total_rows == 0:
        brand_line = f"{brand_name}: the API returned no rows for this date."
        brand_summary = [{"name": brand_name, "rows": 0, "pending": 0}] if brand_name != "All" else []
    else:
        brand_summary = [
            {"name": name, "rows": totals.get(name, 0), "pending": pending.get(name, 0)} for name in names
        ]
        brand_line = "   ".join(
            f"{item['name']}: {item['rows']} rows, {item['pending']} pending" for item in brand_summary
        )

    body = {
        "date": day.isoformat(),
        "brand": brand_name,
        "rows": visible,
        "stats": _stats_rows(scoped),
        "brand_summary": brand_summary,
        "brand_line": brand_line,
        "status_line": status_line,
        "errors": errors,
        "synced_at": synced_at.isoformat() if synced_at else None,
    }
    revision = packed.get("revision")
    if revision:
        body["revision"] = int(revision)
    return body


def _latest_sync(meta: list[dict]):
    latest = None
    for item in meta:
        text = str(item.get("updated_at") or "")
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _matches_status(row: dict, wanted_status: str) -> bool:
    if wanted_status == "OTHER":
        return _stat_key(row) == "other"
    return row.get("status") == wanted_status


def _stat_key(row: dict) -> str:
    status = row.get("status")
    kind = row.get("type")
    if status == "PENDING" and kind == "DEPOSIT":
        return "pending_deposit"
    if status == "PENDING" and kind == "WITHDRAW":
        return "pending_withdraw"
    if status == "PROCESSING":
        return "processing"
    if status == "REJECTED":
        return "rejected"
    if status == "COMPLETED" and kind == "DEPOSIT":
        return "completed_deposit"
    if status == "COMPLETED" and kind == "WITHDRAW":
        return "completed_withdraw"
    if kind == "BONUS":
        return "bonus"
    if kind == "FORFEITED":
        return "forfeited"
    return "other"


def _stats_rows(rows: list[dict]) -> dict:
    keys = (
        "pending_deposit",
        "pending_withdraw",
        "completed_deposit",
        "completed_withdraw",
        "bonus",
        "forfeited",
        "processing",
        "rejected",
        "other",
    )
    totals = {key: [0, Decimal("0")] for key in keys}

    def add(key: str, amount_text: object) -> None:
        totals[key][0] += 1
        try:
            totals[key][1] += Decimal(str(amount_text or "0"))
        except (InvalidOperation, ValueError):
            return

    for row in rows:
        add(_stat_key(row), row.get("amount"))

    stats = {key: {"count": count, "amount": f"{amount:.2f}"} for key, (count, amount) in totals.items()}
    net_amount = totals["completed_deposit"][1] + totals["completed_withdraw"][1]
    net_count = totals["completed_deposit"][0] + totals["completed_withdraw"][0]
    stats["net_completed"] = {"count": net_count, "amount": f"{net_amount:.2f}"}
    stats["row_count"] = {"count": len(rows), "amount": "0.00"}
    return stats
