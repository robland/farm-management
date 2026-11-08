from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.finance.models import (
    BudgetAllocation,
    BudgetLine,
    FinanceCategory,
    FinancialTransaction,
    LedgerEntry,
    TransactionRevision,
    TreasuryAccount,
)

# Financial data is immutable once validated (CLAUDE.md §11, database triggers):
# reversals and corrections go through the API, never through the admin.


class LedgerEntryInline(ReadOnlyTabularInline):
    model = LedgerEntry
    show_change_link = False


class TransactionRevisionInline(ReadOnlyTabularInline):
    model = TransactionRevision
    show_change_link = False


class BudgetAllocationInline(ReadOnlyTabularInline):
    model = BudgetAllocation
    fk_name = "transaction"


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(ReadOnlyAdmin):
    list_display = [
        "business_date",
        "kind",
        "status",
        "amount",
        "currency",
        "category",
        "description",
        "possible_duplicate",
        "farm",
    ]
    list_select_related = ["category", "farm"]
    list_filter = ["kind", "status", "currency", "possible_duplicate", "created_offline"]
    search_fields = ["description", "=id", "=idempotency_key"]
    date_hierarchy = "business_date"
    inlines = [LedgerEntryInline, TransactionRevisionInline, BudgetAllocationInline]


@admin.register(TreasuryAccount)
class TreasuryAccountAdmin(ReadOnlyAdmin):
    list_display = ["name", "kind", "currency", "institution", "is_active", "farm"]
    list_filter = ["kind", "currency", "is_active"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ["transaction", "account", "amount", "currency"]
    list_select_related = ["transaction", "account"]
    search_fields = ["=transaction__id", "account__name"]
    list_filter = ["currency"]


class BudgetLineAllocationInline(ReadOnlyTabularInline):
    model = BudgetAllocation
    fk_name = "budget_line"


@admin.register(BudgetLine)
class BudgetLineAdmin(ReadOnlyAdmin):
    list_display = ["label", "planned_amount", "currency", "category", "campaign", "farm"]
    list_select_related = ["category", "campaign", "farm"]
    list_filter = ["currency"]
    inlines = [BudgetLineAllocationInline]


register_read_only(FinanceCategory, TransactionRevision, BudgetAllocation)
