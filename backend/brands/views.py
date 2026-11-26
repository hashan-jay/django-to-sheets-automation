import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from brands import livecache
from brands.models import SYDNEY, Brand, GoogleSheetSetting, GroupSetting, Transaction, sydney_today
from brands.poller import note_watch, start_poller
from brands.customers import customer_board, start_customer_sync
from brands.sheets import (
    export_pending,
    public_status,
    clear_blocked_sheet,
    save_sheet_url,
    save_start_rows,
    set_sheet_auto_sync,
    set_sheet_blocked,
    set_sheet_writes,
    sync_brands_for_day,
)
from brands.services import (
    bank_accounts,
    bank_ledger,
    bank_ledger_day,
    bank_transfer_accounts,
    create_bank_transfer,
    list_bank_transfers,
    load_dashboard,
    sync_day,
    tally_system_banks,
    transaction_record,
    update_bank_ledger,
)


def _chosen_group(request, body: bool = False) -> str:
    source = request.data if body else request.query_params
    return str(source.get("group") or "KABOOM77").strip() or "KABOOM77"


class GoogleSheetView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(public_status(_chosen_group(request)))

    def post(self, request):
        group = _chosen_group(request, body=True)
        try:
            if "deposit_start_row" in request.data or "withdraw_start_row" in request.data:
                save_start_rows(
                    request.data.get("deposit_start_row"),
                    request.data.get("withdraw_start_row"),
                    request.data.get("slot") or 1,
                    request.data.get("deposit_end_row"),
                    request.data.get("withdraw_end_row"),
                    group,
                )
            else:
                save_sheet_url(str(request.data.get("sheet_url") or ""), request.data.get("slot") or 1, group)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except Exception as exc:
            message = str(exc).splitlines()[0][:500] or "The Google Sheet could not be saved."
            return Response({"detail": message}, status=500)
        written = 0
        if "sheet_url" in request.data:
            try:
                written = export_pending(slot=request.data.get("slot") or 1, group=group)
            except Exception as exc:
                message = str(exc).splitlines()[0][:500] or "The Google Sheet could not be saved."
                return Response({"detail": message}, status=500)
        try:
            body = public_status(group)
        except Exception as exc:
            message = str(exc).splitlines()[0][:500] or "The Google Sheet could not be saved."
            return Response({"detail": message}, status=500)
        body["written_now"] = written
        return Response(body)


class GoogleSheetBlockView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            set_sheet_blocked(request.data.get("slot") or 1, request.data.get("blocked"), _chosen_group(request, True))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(public_status(_chosen_group(request, True)))


class GoogleSheetClearView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            clear_blocked_sheet(request.data.get("slot") or 1, _chosen_group(request, True))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(public_status(_chosen_group(request, True)))


class GoogleSheetAutoSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            set_sheet_auto_sync(request.data.get("slot") or 1, request.data.get("auto_sync"), _chosen_group(request, True))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(public_status(_chosen_group(request, True)))


class GoogleSheetWritesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            set_sheet_writes(
                request.data.get("slot") or 1,
                request.data.get("deposits_enabled") if "deposits_enabled" in request.data else None,
                request.data.get("withdrawals_enabled") if "withdrawals_enabled" in request.data else None,
                _chosen_group(request, True),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(public_status(_chosen_group(request, True)))


class GoogleSheetSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        day = _parse_day(request.data.get("date"))
        try:
            result = sync_brands_for_day(day, request.data.get("slot") or 1, _chosen_group(request, True))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except Exception as exc:
            message = str(exc).splitlines()[0][:500] or "The Google Sheet could not be updated."
            return Response({"detail": message}, status=502)
        return Response(result)


class SheetPipelineView(APIView):
    """Read-only progress of API rows, rows waiting to be written, and rows already written."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        group = _chosen_group(request)
        sheets = [
            row for row in GoogleSheetSetting.objects.filter(group=group, slot__in=(1, 2, 3)).order_by("slot")
            if (row.sheet_url or "").strip() and not row.blocked
        ]
        stored = Transaction.objects.filter(txn_date=day, brand__is_active=True, brand__group=group)
        received = list(
            stored.filter(type__in=["DEPOSIT", "WITHDRAW"])
            .select_related("brand")
            .prefetch_related("sheet_exports")
            .order_by("-created_at", "-id")
        )
        latest = []
        pending = []
        written = []
        for item in received:
            targets = _write_targets(item, sheets)
            exported = {mark.slot for mark in item.sheet_exports.all()}
            sent = [row for row in targets if row.slot in exported]
            waiting = [row for row in targets if row.slot not in exported]
            card = _pipeline_card(item, sent)
            card["unwritten"] = not (targets and not waiting)
            if targets and waiting:
                pending.append(card)
            elif targets and not waiting:
                written.append(card)
            elif _show_in_received(item):
                latest.append(card)
        kind = (request.query_params.get("type") or "ALL").strip().upper()
        if kind not in {"DEPOSIT", "WITHDRAW"}:
            kind = "ALL"
        completed = [item for item in received if item.status == "COMPLETED"]
        if kind != "ALL":
            latest = [card for card in latest if card["type"] == kind]
            pending = [card for card in pending if card["type"] == kind]
            written = [card for card in written if card["type"] == kind]
            completed = [item for item in completed if item.type == kind]
        target_count = len(pending) + len(written)
        return Response({
            "date": day.isoformat(),
            "sheets": [row.sheet_name or f"Google Sheet {row.slot}" for row in sheets],
            "received": {
                "got": len(latest),
                "total": stored.count(),
                "rows": latest[:8],
            },
            "pending": {
                "got": len(pending),
                "total": target_count,
                "rows": pending[:8],
            },
            "written": {
                "got": len(written),
                "total": target_count or len(completed),
                "rows": written[:8],
            },
        })


def _show_in_received(item: Transaction) -> bool:
    """Received lists completed-path deposits and withdrawals only.

    Rejected and other non-writing statuses stay out, and a deposit paid with
    Manual | Online is never listed here.
    """
    if item.type not in {"DEPOSIT", "WITHDRAW"}:
        return False
    if item.status in {"REJECTED", "OTHER"}:
        return False
    if item.type == "DEPOSIT" and (item.method or "").strip().casefold() == "manual | online":
        return False
    return True


def _write_targets(item: Transaction, sheets: list[GoogleSheetSetting]) -> list[GoogleSheetSetting]:
    if item.status != "COMPLETED" or item.type not in {"DEPOSIT", "WITHDRAW"}:
        return []
    targets = []
    for row in sheets:
        if item.type == "DEPOSIT" and not row.deposits_enabled:
            continue
        if item.type == "WITHDRAW" and not row.withdrawals_enabled:
            continue
        targets.append(row)
    return targets


def _pipeline_card(item: Transaction, sent: list[GoogleSheetSetting]) -> dict:
    moment = item.created_at
    when = ""
    if moment is not None:
        local = moment.astimezone(SYDNEY) if timezone_is_aware(moment) else moment
        when = local.strftime("%H:%M")
    return {
        "id": item.external_id,
        "brand": item.brand.name,
        "type": item.type,
        "status": item.status,
        "amount": f"{item.amount:.2f}",
        "time": when,
        "name": item.player_name or item.username,
        "sheets": [row.sheet_name or f"Google Sheet {row.slot}" for row in sent],
    }


def timezone_is_aware(moment) -> bool:
    from django.utils import timezone
    return timezone.is_aware(moment)


class SheetAnalyticsView(APIView):
    """Compare saved deposits and withdrawals with the rows this app has written.

    Reads the database only. It does not open Google Sheets or change the writer.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = _parse_day(request.query_params.get("date"))
        sheets = list(GoogleSheetSetting.objects.filter(group=_chosen_group(request), slot__in=(1, 2, 3)).order_by("slot"))
        saved = [row for row in sheets if (row.sheet_url or "").strip()]
        group = _chosen_group(request)
        transactions = (
            Transaction.objects.filter(txn_date=day, type__in=["DEPOSIT", "WITHDRAW"], brand__is_active=True, brand__group=group)
            .select_related("brand")
            .prefetch_related("sheet_exports")
            .order_by("-created_at", "-id")
        )
        rows = []
        counts = {
            "all_deposit": 0,
            "all_withdraw": 0,
            "sent_deposit": 0,
            "sent_withdraw": 0,
            "missing_deposit": 0,
            "missing_withdraw": 0,
        }
        for item in transactions:
            exported = {mark.slot for mark in item.sheet_exports.all()}
            sent = [row for row in saved if row.slot in exported]
            missing = []
            for row in saved:
                if row.slot in exported:
                    continue
                missing.append({"slot": row.slot, "sheet": row.sheet_name or f"Google Sheet {row.slot}", "reason": _unsent_reason(item, row)})
            if not saved and item.status == "COMPLETED":
                missing.append({"slot": 0, "sheet": "Google Sheet", "reason": "No Google Sheet link is saved."})
            kind = "deposit" if item.type == "DEPOSIT" else "withdraw"
            counts[f"all_{kind}"] += 1
            if sent:
                counts[f"sent_{kind}"] += 1
            if missing:
                counts[f"missing_{kind}"] += 1
            rows.append({
                "id": item.external_id,
                "brand": item.brand.name,
                "type": item.type,
                "status": item.status,
                "amount": f"{item.amount:.2f}",
                "username": item.username,
                "name": item.player_name,
                "time": item.created_at.astimezone(SYDNEY).strftime("%Y-%m-%d %H:%M") if item.created_at else "",
                "sent_sheets": [row.sheet_name or f"Google Sheet {row.slot}" for row in sent],
                "missing": missing,
            })
        return Response({
            "date": day.isoformat(),
            "sheets": [
                {
                    "slot": row.slot,
                    "name": row.sheet_name or f"Google Sheet {row.slot}",
                    "saved": bool((row.sheet_url or "").strip()),
                }
                for row in sheets
            ],
            "counts": counts,
            "rows": rows,
        })


def _unsent_reason(item: Transaction, row: GoogleSheetSetting) -> str:
    label = row.sheet_name or f"Google Sheet {row.slot}"
    if item.status != "COMPLETED":
        return f"Status is {item.status}. Only completed deposits and withdrawals are written."
    if item.type == "DEPOSIT" and not row.deposits_enabled:
        return f"Deposit writing is disabled on {label}."
    if item.type == "WITHDRAW" and not row.withdrawals_enabled:
        return f"Withdrawal writing is disabled on {label}."
    if row.blocked:
        return f"{label} is blocked, so live writing is paused."
    if not row.auto_sync:
        return f"Auto Sync is off on {label}. It is sent only by Sync with Google Sheet."
    if (row.last_error or "").strip():
        return f"{label} last reported: {row.last_error.strip()[:180]}"
    return f"This completed row is not on {label}. Sheet Analytics lists it here until the writer adds it."


class TallySystemBanksView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        day = _parse_day(request.data.get("date"))
        try:
            result = tally_system_banks(day)
        except Exception as exc:
            message = str(exc).splitlines()[0][:500] or "The system banks could not be tallied."
            return Response({"detail": message}, status=502)
        return Response(result)


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
        return _live_response(customer_board(day, brand_name, query, _parse_page(request.query_params.get("page")), _chosen_group(request)))


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
        errors = sync_day(day)
        detail = " ".join(errors)[:500]
        return Response({"ok": not errors, "date": day.isoformat(), "detail": detail})


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
        if GroupSetting.objects.filter(code=group_name).exists() or group_name in {choice for choice, _label in Brand.GROUPS}:
            allowed = set(Brand.objects.filter(is_active=True, group=group_name).values_list("name", flat=True))
        else:
            allowed = set()
        if brand_name != "All" and brand_name not in allowed:
            allowed = set()
        rows = [row for row in rows if row.get("brand") in allowed]
        brands_meta = [item for item in brands_meta if item.get("name") in allowed]
    by_brand: dict[str, list] = {}
    for row in rows:
        by_brand.setdefault(row.get("brand") or "", []).append(row)
    stats_by_brand = {name: _stats_rows(items) for name, items in by_brand.items() if name}
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
        "stats_by_brand": stats_by_brand,
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


def _kaboom_google_email() -> str:
    from brands.sheets import CREDENTIALS
    import json

    try:
        payload = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("client_email") or "").strip()


class GroupListView(APIView):
    """Main groups. Creating one does not change KABOOM77 sheets or brands."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        GroupSetting.objects.get_or_create(code="KABOOM77")
        codes = list(GroupSetting.objects.order_by("code").values_list("code", flat=True))
        codes.sort(key=lambda code: (code != "KABOOM77", code.casefold()))
        return Response({"groups": codes})

    def post(self, request):
        name = " ".join(str(request.data.get("name") or "").split())
        if not name:
            return Response({"detail": "Enter a group name."}, status=400)
        if len(name) > 64:
            return Response({"detail": "Use a group name of 64 characters or less."}, status=400)
        if GroupSetting.objects.filter(code__iexact=name).exists():
            return Response({"detail": "That group already exists."}, status=400)
        GroupSetting.objects.create(code=name)
        from brands.sheets import ensure_sheet_slots
        ensure_sheet_slots(name)
        return Response({"code": name})


class SystemSettingsView(APIView):
    """Group Google account and brand API keys. Does not start or stop the live writer."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = _chosen_group(request)
        if not GroupSetting.objects.filter(code=code).exists() and code != "KABOOM77":
            code = "KABOOM77"
        GroupSetting.objects.get_or_create(code=code)
        return Response({"groups": [_group_settings(code)]})

    def post(self, request):
        code = str(request.data.get("group") or "").strip()
        if not code or not GroupSetting.objects.filter(code=code).exists():
            return Response({"detail": "Choose a group that exists."}, status=400)
        setting, _created = GroupSetting.objects.get_or_create(code=code)
        email = str(request.data.get("google_email") or "").strip()
        if email:
            setting.google_email = email
            setting.save(update_fields=["google_email"])
        brand_body = request.data.get("brand") if isinstance(request.data.get("brand"), dict) else {}
        if any(str(brand_body.get(key) or "").strip() for key in ("name", "access_id", "token", "domain", "merchant_id")):
            saved = _save_group_brand(code, brand_body)
            if isinstance(saved, Response):
                return saved
        return Response(_group_settings(code))

    def delete(self, request):
        code = str(request.data.get("group") or "KABOOM77").strip()
        name = str(request.data.get("name") or "").strip()
        brand = Brand.objects.filter(group=code, name=name).first()
        if brand is None:
            return Response({"detail": "That API key was not found."}, status=404)
        if brand.is_active and code == "KABOOM77":
            return Response(
                {"detail": f"{brand.name} is the running API key. It stays in place so live writing is not stopped."},
                status=400,
            )
        brand.delete()
        return Response(_group_settings(code))


def _group_settings(code: str) -> dict:
    setting, _created = GroupSetting.objects.get_or_create(code=code)
    email = (setting.google_email or "").strip()
    if not email and code == "KABOOM77":
        email = _kaboom_google_email()
    brands = Brand.objects.filter(group=code).order_by("sort_order", "name")
    return {
        "code": code,
        "google_email": email,
        "live": code == "KABOOM77",
        "brands": [
            {
                "name": brand.name,
                "domain": brand.domain,
                "access_id": brand.access_id,
                "merchant_id": brand.merchant_id,
                "token": brand.token,
                "active": brand.is_active,
            }
            for brand in brands
        ],
    }


def _save_group_brand(code: str, body: dict):
    name = str(body.get("name") or "").strip()
    access_id = str(body.get("access_id") or "").strip()
    token = str(body.get("token") or "").strip()
    merchant_id = str(body.get("merchant_id") or "").strip()
    domain = str(body.get("domain") or "").strip()
    if not name or not access_id or not token:
        return Response({"detail": "Brand name, access ID, and token are required."}, status=400)
    previous = str(body.get("previous_name") or "").strip()
    existing = Brand.objects.filter(name=previous).first() if previous else Brand.objects.filter(name=name).first()
    if existing is None:
        existing = Brand.objects.filter(name=name).first()
    if existing is not None and existing.group != code:
        return Response({"detail": f"{name} already belongs to {existing.group or 'another group'}."}, status=400)
    if existing is None and not domain:
        return Response({"detail": "A new brand needs its API domain."}, status=400)
    if existing is None:
        Brand.objects.create(
            name=name,
            domain=domain,
            access_id=access_id[:32],
            merchant_id=merchant_id[:32],
            token=token[:128],
            group=code,
            is_active=True,
        )
        _write_brand_env(name, domain, access_id[:32], merchant_id[:32], token[:128])
        return None
    if previous and previous != name:
        taken = Brand.objects.filter(name=name).exclude(pk=existing.pk).exists()
        if taken:
            return Response({"detail": f"{name} is already used by another brand."}, status=400)
        existing.name = name
    existing.access_id = access_id[:32]
    existing.token = token[:128]
    if merchant_id:
        existing.merchant_id = merchant_id[:32]
    if domain:
        existing.domain = domain
    existing.group = code
    existing.save(update_fields=["name", "access_id", "token", "merchant_id", "domain", "group"])
    _write_brand_env(existing.name, existing.domain, existing.access_id, existing.merchant_id, existing.token)
    return None


def _write_brand_env(name: str, domain: str, access_id: str, merchant_id: str, token: str) -> None:
    """Keep the brand's .env lines in step with the key saved from System Settings."""
    prefix = "".join(ch for ch in name.upper() if ch.isalnum())
    if not prefix:
        return
    from pathlib import Path
    path = Path(settings.BASE_DIR) / ".env"
    if not path.is_file():
        return
    updates = {
        f"{prefix}_DOMAIN": domain,
        f"{prefix}_ACCESS_ID": access_id,
        f"{prefix}_MERCHANT_ID": merchant_id,
        f"{prefix}_TOKEN": token,
    }
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    seen = set()
    written = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            written.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            written.append(line)
    for key, value in updates.items():
        if key not in seen:
            written.append(f"{key}={value}")
    path.write_text("\n".join(written) + ("\n" if original.endswith("\n") else ""), encoding="utf-8")
