from django.contrib import admin

from brands.models import BankTransfer, Brand, BrandSync, Customer, CustomerSync, Transaction


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "domain", "merchant_id", "is_active", "sort_order")
    search_fields = ("name", "domain")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("external_id", "brand", "txn_date", "status", "type", "amount", "username")
    list_filter = ("brand", "status", "type", "txn_date")
    search_fields = ("external_id", "username", "player_name")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("username", "name", "brand", "status", "registered_at", "mobile")
    list_filter = ("brand", "status")
    search_fields = ("username", "name", "mobile", "external_id", "email")


@admin.register(CustomerSync)
class CustomerSyncAdmin(admin.ModelAdmin):
    list_display = ("brand", "next_page", "total_pages", "updated_at", "message")


@admin.register(BankTransfer)
class BankTransferAdmin(admin.ModelAdmin):
    list_display = (
        "transfer_date",
        "created_on",
        "from_bank_name",
        "from_account_name",
        "to_bank_name",
        "to_account_name",
        "amount",
        "remarks",
        "created_at",
    )
    list_filter = ("transfer_date", "created_on")
    search_fields = ("from_bank_name", "from_account_name", "to_bank_name", "to_account_name", "remarks")


class BrandSyncAdmin(admin.ModelAdmin):
    list_display = ("brand", "day", "row_count", "updated_at", "message")
    list_filter = ("day", "brand")
