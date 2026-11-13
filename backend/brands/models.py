from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models

SYDNEY = ZoneInfo("Australia/Sydney")


class Brand(models.Model):
    GROUP_SOLO = "SOLO - KABOOM"
    GROUP_AK = "GROUP AK"
    GROUP_U = "GROUP U"
    GROUP_Y = "GROUP Y"
    GROUP_AH = "GROUP AH"
    GROUPS = (
        (GROUP_SOLO, GROUP_SOLO),
        (GROUP_AK, GROUP_AK),
        (GROUP_U, GROUP_U),
        (GROUP_Y, GROUP_Y),
        (GROUP_AH, GROUP_AH),
    )

    name = models.CharField(max_length=64, unique=True)
    domain = models.CharField(max_length=255)
    access_id = models.CharField(max_length=32)
    merchant_id = models.CharField(max_length=32, blank=True)
    token = models.CharField(max_length=128)
    group = models.CharField(max_length=32, blank=True, choices=GROUPS)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


def is_gateway_method(value: object) -> bool:
    """AtasPay and AmoPay (including AmoPayRamp) are payment methods, not company banks."""
    text = "".join(str(value or "").casefold().split())
    return "ataspay" in text or "amopay" in text


class Transaction(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="transactions")
    external_id = models.CharField(max_length=64)
    txn_date = models.DateField(db_index=True)
    status = models.CharField(max_length=32, db_index=True)
    type = models.CharField(max_length=32, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    username = models.CharField(max_length=128, blank=True)
    player_name = models.CharField(max_length=255, blank=True)
    mobile = models.CharField(max_length=64, blank=True)
    bank = models.CharField(max_length=128, blank=True)
    bank_name = models.CharField(max_length=128, blank=True)
    bank_account_name = models.CharField(max_length=255, blank=True)
    acc_name = models.CharField(max_length=255, blank=True)
    acc_no = models.CharField(max_length=64, blank=True)
    bsb = models.CharField(max_length=32, blank=True)
    pay_id = models.CharField(max_length=128, blank=True)
    method = models.CharField(max_length=128, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["brand", "external_id"], name="uniq_brand_txn"),
        ]
        indexes = [
            models.Index(fields=["txn_date", "brand", "status"]),
        ]

    def display(self) -> dict:
        return {
            "time": _clock(self.created_at),
            "id": self.external_id,
            "username": self.username,
            "name": self.player_name,
            "mobile": self.mobile,
            "amount": f"{self.amount:.2f}",
            "type": self.type,
            "bank_name": "" if is_gateway_method(self.method) else (self.bank_name if self.status == "COMPLETED" and self.type in {"DEPOSIT", "WITHDRAW"} else ""),
            "bank_account_name": "" if is_gateway_method(self.method) else (self.bank_account_name if self.status == "COMPLETED" and self.type in {"DEPOSIT", "WITHDRAW"} else ""),
            "payment_method": self.method if is_gateway_method(self.method) else ("" if (self.bank_name or self.bank_account_name) else self.method),
            "bank": self.bank,
            "acc_name": self.acc_name,
            "acc_no": self.acc_no,
            "bsb": self.bsb,
            "pay_id": self.pay_id,
            "brand": self.brand.name,
            "created": _clock(self.created_at),
            "processed": _clock(self.processed_at),
            "status": self.status,
            "detail": str(getattr(self, "detail_short", None) or self.detail or "")[:160],
        }


class Customer(models.Model):
    """A player account on one brand, copied from /users/getAllUsers."""

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="customers")
    external_id = models.CharField(max_length=64)
    username = models.CharField(max_length=128, blank=True)
    name = models.CharField(max_length=255, blank=True)
    mobile = models.CharField(max_length=64, blank=True)
    email = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, blank=True)
    account_type = models.CharField(max_length=32, blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)
    visited_at = models.DateTimeField(null=True, blank=True)
    cash_site_at = models.DateTimeField(null=True, blank=True)
    cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lifetime_deposit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lifetime_deposit_count = models.PositiveIntegerField(default=0)
    lifetime_withdraw = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lifetime_withdraw_count = models.PositiveIntegerField(default=0)
    withdraw_synced_at = models.DateTimeField(null=True, blank=True)
    referrer_name = models.CharField(max_length=128, blank=True)
    referrer_code = models.CharField(max_length=64, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    bank_name = models.CharField(max_length=128, blank=True)
    bank_account_name = models.CharField(max_length=255, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)
    bank_bsb = models.CharField(max_length=32, blank=True)
    pay_id = models.CharField(max_length=128, blank=True)
    bank_locked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["brand", "external_id"], name="uniq_brand_customer"),
        ]
        indexes = [
            models.Index(fields=["brand", "registered_at"], name="customer_brand_registered"),
            models.Index(fields=["username"], name="customer_username"),
        ]

    def __str__(self) -> str:
        return self.username or self.external_id


class CustomerSync(models.Model):
    """How far the register backfill has read for one brand. Pages are oldest first."""

    brand = models.OneToOneField(Brand, on_delete=models.CASCADE, related_name="customer_sync")
    next_page = models.PositiveIntegerField(default=0)
    total_pages = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.brand.name} {self.next_page}/{self.total_pages}"


class BrandSync(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="syncs")
    day = models.DateField()
    message = models.TextField(blank=True)
    row_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["brand", "day"], name="uniq_brand_sync_day"),
        ]


class CompanyBank(models.Model):
    """Organization bank account shared across brands, keyed by the brand API bank id."""

    external_id = models.CharField(max_length=32, unique=True)
    bank_name = models.CharField(max_length=128, blank=True)
    account_name = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return self.account_name or self.external_id


class BankLedgerSetting(models.Model):
    """Manual status and limit for one bank account. Balances are not stored here."""

    STATUSES = (
        ("Block", "Block"),
        ("Withdraw only", "Withdraw only"),
        ("Deposit only", "Deposit only"),
        ("Both", "Both"),
        ("Active", "Active"),
        ("Inactive", "Inactive"),
    )

    bank_name = models.CharField(max_length=128)
    account_name = models.CharField(max_length=255)
    status = models.CharField(max_length=32, blank=True, choices=STATUSES)
    limit_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bank_name", "account_name"], name="uniq_bank_ledger_account"),
        ]

    def __str__(self) -> str:
        return f"{self.bank_name} · {self.account_name}"


class BankTransfer(models.Model):
    """Money moved by hand from one bank account to another.

    transfer_date is the day the finance team moved the money in the bank apps.
    created_on is the Sydney day this row was entered here. Balances follow
    transfer_date, not the day the row was typed in.
    """

    transfer_date = models.DateField(db_index=True)
    created_on = models.DateField(db_index=True)
    from_bank_name = models.CharField(max_length=128)
    from_account_name = models.CharField(max_length=255)
    to_bank_name = models.CharField(max_length=128)
    to_account_name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    remarks = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_transfers",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["from_bank_name", "from_account_name", "transfer_date"], name="bank_xfer_from_day"),
            models.Index(fields=["to_bank_name", "to_account_name", "transfer_date"], name="bank_xfer_to_day"),
        ]

    def __str__(self) -> str:
        return f"{self.transfer_date} {self.from_bank_name} → {self.to_bank_name} {self.amount}"


class GoogleSheetSetting(models.Model):
    """One spreadsheet the web app writes to. Slots 1–3 are Google Sheet 1, 2, and 3.

    Deposit and withdrawal start rows are shared and stored on slot 1.
    """

    slot = models.PositiveSmallIntegerField(default=1, unique=True)
    sheet_url = models.URLField(max_length=500, blank=True)
    sheet_name = models.CharField(max_length=200, blank=True, default="")
    blocked = models.BooleanField(default=False)
    deposit_start_row = models.PositiveIntegerField(default=105)
    withdraw_start_row = models.PositiveIntegerField(default=1024)
    last_error = models.TextField(blank=True)
    last_written_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slot"]

    def __str__(self) -> str:
        return self.sheet_url or f"Google Sheet {self.slot}"


class SheetExport(models.Model):
    """A completed deposit or withdrawal already written to one Google Sheet slot."""

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="sheet_exports")
    slot = models.PositiveSmallIntegerField(default=1)
    written_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["transaction", "slot"], name="sheet_export_once"),
        ]


def sydney_today():
    return datetime.now(SYDNEY).date()


def _clock(value) -> str:
    """Sydney wall time for a stored instant. The database value is left unchanged."""
    if value is None:
        return ""
    from django.utils import timezone

    local = value.astimezone(SYDNEY) if timezone.is_aware(value) else value.replace(tzinfo=SYDNEY)
    return local.strftime("%Y-%m-%d %H:%M")
