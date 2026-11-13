from django.urls import path

from brands.views import (
    BankAccountsView,
    BankLedgerDayView,
    BankLedgerView,
    BankTransferAccountView,
    BankTransferListView,
    BrandListView,
    CustomersView,
    DashboardView,
    GoogleSheetBlockView,
    GoogleSheetSyncView,
    GoogleSheetView,
    SyncView,
    TallySystemBanksView,
    TransactionDetailView,
)

urlpatterns = [
    path("brands/", BrandListView.as_view()),
    path("dashboard/", DashboardView.as_view()),
    path("customers/", CustomersView.as_view()),
    path("bank-accounts/", BankAccountsView.as_view()),
    path("bank-ledger/", BankLedgerView.as_view()),
    path("bank-ledger/day/", BankLedgerDayView.as_view()),
    path("bank-transfers/", BankTransferListView.as_view()),
    path("bank-transfers/accounts/", BankTransferAccountView.as_view()),
    path("transactions/detail/", TransactionDetailView.as_view()),
    path("sync/", SyncView.as_view()),
    path("google-sheet/", GoogleSheetView.as_view()),
    path("google-sheet/block/", GoogleSheetBlockView.as_view()),
    path("google-sheet/sync/", GoogleSheetSyncView.as_view()),
    path("banks/tally/", TallySystemBanksView.as_view()),
]
