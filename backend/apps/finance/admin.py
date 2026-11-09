import uuid
from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.core.admin_services import (
    ReasonForm,
    ServiceAdmin,
    ServiceForm,
    platform_context,
    service_action,
)
from apps.core.tenancy import TenantContext
from apps.finance import services
from apps.finance.models import (
    BudgetAllocation,
    BudgetLine,
    FinanceCategory,
    FinancialTransaction,
    LedgerEntry,
    Loan,
    TransactionRevision,
    TreasuryAccount,
)

# Financial data is immutable once validated (CLAUDE.md §11, database triggers). The
# admin records, validates, rejects, reverses and corrects through the services, exactly
# like the API: a correction is a reversal plus a new linked transaction, never an edit.

K = FinancialTransaction.Kind
ST = FinancialTransaction.Status


class IdempotentForm(forms.Form):
    """The key is generated when the form is displayed: submitting twice records once."""

    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class LedgerEntryInline(ReadOnlyTabularInline):
    model = LedgerEntry
    show_change_link = False


class TransactionRevisionInline(ReadOnlyTabularInline):
    model = TransactionRevision
    show_change_link = False


class BudgetAllocationInline(ReadOnlyTabularInline):
    model = BudgetAllocation
    fk_name = "transaction"


class TransactionForm(ServiceForm):
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4, required=False)
    kind = forms.ChoiceField(
        label="Type",
        choices=[
            (K.EXPENSE, K.EXPENSE.label),
            (K.INCOME, K.INCOME.label),
            (K.TRANSFER, K.TRANSFER.label),
            (K.FUNDING, K.FUNDING.label),
            (K.REPAYMENT, K.REPAYMENT.label),
        ],
        help_text="Un apport sur un compte de membre est saisi par son titulaire (API).",
    )
    account = forms.ModelChoiceField(label="Compte", queryset=TreasuryAccount.objects.all())
    to_account = forms.ModelChoiceField(
        label="Compte destinataire (transfert)",
        queryset=TreasuryAccount.objects.all(),
        required=False,
    )
    currency = forms.CharField(
        label="Devise", max_length=3, required=False, help_text="Vide : devise du compte."
    )
    reason = forms.CharField(label="Motif de la modification", required=False)


class CorrectionForm(forms.Form):
    reason = forms.CharField(label="Motif", widget=forms.Textarea(attrs={"rows": 2}))
    amount = forms.DecimalField(label="Montant corrigé", required=False)
    business_date = forms.DateField(label="Date corrigée", required=False)
    description = forms.CharField(label="Libellé corrigé", required=False)


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(ServiceAdmin):
    """Expenses, incomes, transfers, fundings and loan repayments (Q35).

    Only a submitted transaction can be amended; a member's contribution is recorded by
    its holder and validated here.
    """

    form = TransactionForm
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
    add_fields = [
        "idempotency_key",
        "kind",
        "business_date",
        "amount",
        "currency",
        "account",
        "to_account",
        "category",
        "description",
        "counterparty",
        "campaign",
        "plan",
        "crop_cycle",
        "loan",
    ]
    change_fields = ["amount", "business_date", "category", "description", "reason"]
    actions = ["validate", "reject", "reverse", "correct"]

    def can_change(self, obj: Any) -> bool:
        return obj.status == ST.SUBMITTED

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> FinancialTransaction:
        data = {k: v for k, v in data.items() if v not in (None, "")}
        data.setdefault("idempotency_key", uuid.uuid4())
        recorder = {
            K.TRANSFER: services.record_transfer,
            K.FUNDING: services.record_funding,
            K.REPAYMENT: services.record_repayment,
        }.get(data["kind"])
        if recorder is None:
            data.pop("to_account", None)
            recorder = services.record_transaction
        tx, _ = recorder(ctx, data=data)
        return tx

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        reason = changes.pop("reason", "")
        if not changes:
            return None
        return services.amend_transaction(
            ctx, tx_id=obj.id, expected_version=expected_version, changes=changes, reason=reason
        )

    @service_action("Valider les transactions")
    def validate(self, ctx: TenantContext, obj: FinancialTransaction) -> None:
        services.validate_transaction(ctx, tx_id=obj.id, expected_version=obj.version)

    @service_action("Rejeter les transactions", form=ReasonForm)
    def reject(self, ctx: TenantContext, obj: FinancialTransaction, reason: str) -> None:
        services.reject_transaction(ctx, tx_id=obj.id, expected_version=obj.version, reason=reason)

    @service_action("Annuler (contre-passation)", form=ReasonForm)
    def reverse(self, ctx: TenantContext, obj: FinancialTransaction, reason: str) -> None:
        services.reverse_transaction(ctx, tx_id=obj.id, reason=reason)

    @service_action("Corriger (annulation + nouvelle transaction liée)", form=CorrectionForm)
    def correct(
        self, ctx: TenantContext, obj: FinancialTransaction, reason: str, **values: Any
    ) -> None:
        corrected = {k: v for k, v in values.items() if v not in (None, "")}
        services.correct_transaction(ctx, tx_id=obj.id, reason=reason, corrected=corrected)


class OpeningForm(IdempotentForm):
    balance = forms.DecimalField(label="Solde d'ouverture")
    business_date = forms.DateField(label="Date")


@admin.register(TreasuryAccount)
class TreasuryAccountAdmin(ServiceAdmin):
    """Main and operating accounts; member accounts are opened by their holder (Q35)."""

    list_display = ["name", "role", "holder", "kind", "currency", "is_active", "farm"]
    list_select_related = ["holder", "farm"]
    list_filter = ["role", "kind", "currency", "is_active"]
    add_fields = ["name", "kind", "role", "currency", "institution", "account_ref", "is_active"]
    change_fields = ["name", "kind", "institution", "account_ref", "is_active"]
    actions = ["opening", "set_main"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> TreasuryAccount:
        return services.create_account(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_account(
            ctx, account_id=obj.id, expected_version=expected_version, changes=changes
        )

    @service_action("Enregistrer le solde d'ouverture", form=OpeningForm)
    def opening(
        self,
        ctx: TenantContext,
        obj: TreasuryAccount,
        balance: Any,
        business_date: Any,
        idempotency_key: uuid.UUID,
    ) -> None:
        # One key per account: the same confirmation applied to several accounts stays distinct.
        key = uuid.uuid5(idempotency_key, str(obj.id))
        services.record_opening(
            ctx, account=obj, balance=balance, business_date=business_date, idempotency_key=key
        )

    @service_action("Définir comme compte principal (trésorerie)")
    def set_main(self, ctx: TenantContext, obj: TreasuryAccount) -> None:
        services.set_main_account(ctx, account_id=obj.id)


@admin.register(FinanceCategory)
class FinanceCategoryAdmin(ServiceAdmin):
    list_display = ["name", "kind", "code", "is_capex", "is_active", "organization"]
    list_filter = ["kind", "is_capex", "is_active"]
    scope = "organization"
    add_fields = ["kind", "code", "name", "parent", "is_capex", "is_active"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> FinanceCategory:
        return services.create_category(ctx, data=data)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    """Entries are written by the transaction services only."""

    list_display = ["transaction", "account", "amount", "currency"]
    list_select_related = ["transaction", "account"]
    search_fields = ["=transaction__id", "account__name"]
    list_filter = ["currency"]


@admin.register(Loan)
class LoanAdmin(ServiceAdmin):
    """Loans: disbursed by fundings and paid back by repayments, recorded as transactions."""

    list_display = ["lender", "principal", "outstanding", "currency", "started_on", "farm"]
    list_select_related = ["farm"]
    add_fields = ["lender", "counterparty", "principal", "currency", "started_on", "notes"]

    @admin.display(description="Capital restant dû")
    def outstanding(self, obj: Loan) -> Any:
        # One aggregate per row: a farm has a handful of loans.
        return services.loan_position(obj)["outstanding"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Loan:
        return services.create_loan(ctx, data=data)


class BudgetLineAllocationInline(ReadOnlyTabularInline):
    model = BudgetAllocation
    fk_name = "budget_line"


@admin.register(BudgetLine)
class BudgetLineAdmin(ServiceAdmin):
    list_display = ["label", "planned_amount", "currency", "category", "campaign", "farm"]
    list_select_related = ["category", "campaign", "farm"]
    list_filter = ["currency"]
    inlines = [BudgetLineAllocationInline]
    add_fields = ["campaign", "plan_version", "category", "label", "planned_amount", "currency"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> BudgetLine:
        return services.create_budget_line(ctx, data=data)


@admin.register(BudgetAllocation)
class BudgetAllocationAdmin(ServiceAdmin):
    """Explicit link expense → budget line (budget versus actual, CLAUDE.md §11)."""

    scope = "budget_line"
    add_fields = ["transaction", "amount"]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        line = obj.budget_line
        return platform_context(request, organization_id=line.organization_id, farm_id=line.farm_id)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> BudgetAllocation:
        return services.allocate(
            ctx,
            tx_id=data["transaction"].id,
            budget_line_id=data["budget_line"].id,
            amount=data["amount"],
        )


register_read_only(TransactionRevision)
