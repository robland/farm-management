"""Treasury: accounts, transactions as ledger entries, loans, budgets (ARCHITECTURE.md §9).

Invariants (CLAUDE.md §11):
- Amounts are NUMERIC/Decimal, never floats; each transaction keeps its currency.
- A balance is the sum of the ledger entries of validated (or reversed) transactions.
- Transfers are two entries and never count as income or expense.
- Fundings (member contributions, loan disbursements) and loan repayments move money
  but are neither income nor expense: they never enter the campaign margin (Q35).
- Validated transactions are never updated nor deleted: corrections are reversals
  and new entries (enforced by services AND database triggers, migration 0002).
"""

from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.core.models import (
    AuthoredModel,
    FarmScopedModel,
    OrgScopedModel,
    TimestampedModel,
    UUIDModel,
    VersionedModel,
)
from apps.organizations.models import currency_validator

MONEY: dict[str, Any] = {"max_digits": 19, "decimal_places": 4}


class TreasuryAccount(FarmScopedModel, AuthoredModel, VersionedModel):
    class Kind(models.TextChoices):
        CASH = "cash", "Caisse espèces"
        BANK = "bank", "Compte bancaire"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        OTHER = "other", "Autre"

    class Role(models.TextChoices):
        # The farm treasury: fed by the members' accounts, pays the expenses (Q35).
        MAIN = "main", "Compte principal (trésorerie)"
        # Funds contributed by one member, then transferred to the main account.
        MEMBER = "member", "Compte de membre"
        # Any other farm account, e.g. a field cash box fed from the main account.
        OPERATING = "operating", "Compte d'exploitation"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OPERATING)
    holder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Titulaire d'un compte de membre.",
    )
    currency = models.CharField(max_length=3, validators=[currency_validator])
    institution = models.CharField(max_length=150, blank=True)
    account_ref = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["farm", "name"], name="treasury_account_name_unique"),
            models.UniqueConstraint(
                fields=["farm"],
                condition=models.Q(role="main"),
                name="treasury_one_main_account",
            ),
            models.UniqueConstraint(
                fields=["farm", "holder", "currency"],
                condition=models.Q(role="member"),
                name="treasury_one_member_account_per_currency",
            ),
            models.CheckConstraint(
                condition=(models.Q(role="member") & models.Q(holder__isnull=False))
                | (~models.Q(role="member") & models.Q(holder__isnull=True)),
                name="treasury_holder_iff_member",
            ),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.currency})"


class FinanceCategory(OrgScopedModel, VersionedModel):
    class Kind(models.TextChoices):
        EXPENSE = "expense", "Dépense"
        INCOME = "income", "Recette"
        # Fundings: member contributions, loans (Q35). A subsidy is an income.
        INVESTMENT = "investment", "Investissement (apports et financements)"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    is_active = models.BooleanField(default=True)
    # Expense for a durable asset (machine, irrigation): reported apart from the campaign
    # charges and excluded from the campaign margin. No depreciation yet (Q35).
    is_capex = models.BooleanField("Dépense d'investissement", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "code"], name="finance_category_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(is_capex=False) | models.Q(kind="expense"),
                name="finance_category_capex_is_expense",
            ),
        ]
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return self.name


class Loan(FarmScopedModel, AuthoredModel, VersionedModel):
    """A borrowing: disbursed by funding transactions, paid back by repayments (Q35).

    Outstanding principal = validated disbursements − validated repayments (computed,
    never stored). Interest is recorded as an expense; no repayment schedule yet.
    """

    lender = models.CharField(max_length=200)
    counterparty = models.ForeignKey(
        "inventory.Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    principal = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    started_on = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(principal__gt=0), name="loan_principal_positive"
            )
        ]
        ordering = ["-started_on"]

    def __str__(self) -> str:
        return f"{self.lender} : {self.principal} {self.currency}"


class FinancialTransaction(FarmScopedModel, AuthoredModel, VersionedModel):
    class Kind(models.TextChoices):
        EXPENSE = "expense", "Dépense"
        INCOME = "income", "Recette"
        TRANSFER = "transfer", "Transfert"
        REVERSAL = "reversal", "Annulation"
        OPENING = "opening", "Solde d'ouverture"
        FUNDING = "funding", "Apport / financement"
        REPAYMENT = "repayment", "Remboursement d'emprunt"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Soumise"
        VALIDATED = "validated", "Validée"
        REJECTED = "rejected", "Rejetée"
        REVERSED = "reversed", "Annulée"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices)
    business_date = models.DateField()
    amount = models.DecimalField(**MONEY)  # absolute value; the sign is carried by entries
    currency = models.CharField(max_length=3, validators=[currency_validator])
    category = models.ForeignKey(
        FinanceCategory, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    description = models.TextField(blank=True)
    counterparty = models.ForeignKey(
        "inventory.Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    campaign = models.ForeignKey(
        "production_plans.Campaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    plan = models.ForeignKey(
        "production_plans.ProductionPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    crop_cycle = models.ForeignKey(
        "production_plans.CropCycle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal"
    )
    corrects = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    # Disbursement (funding) or repayment of a loan.
    loan = models.ForeignKey(
        Loan, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    idempotency_key = models.UUIDField()
    created_offline = models.BooleanField(default=False)
    device = models.ForeignKey(
        "users.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    client_created_at = models.DateTimeField(null=True, blank=True)
    possible_duplicate = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=1)
    attachments = models.ManyToManyField("files.StoredFile", blank=True, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "idempotency_key"], name="transaction_idempotency_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="transaction_amount_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(kind__in=["expense", "income", "funding"])
                | models.Q(category__isnull=False),
                name="transaction_category_required",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="repayment") | models.Q(loan__isnull=False),
                name="transaction_repayment_has_loan",
            ),
        ]
        indexes = [
            models.Index(fields=["farm", "business_date"]),
            models.Index(fields=["farm", "status"]),
            models.Index(fields=["farm", "campaign"]),
        ]
        ordering = ["-business_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount} {self.currency} ({self.status})"


class LedgerEntry(UUIDModel):
    transaction = models.ForeignKey(
        FinancialTransaction, on_delete=models.PROTECT, related_name="entries"
    )
    account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="entries")
    amount = models.DecimalField(**MONEY)  # signed
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="ledger_entry_non_zero")
        ]
        indexes = [models.Index(fields=["account", "transaction"])]

    def __str__(self) -> str:
        return f"{self.account_id}: {self.amount}"


class TransactionRevision(UUIDModel):
    """Snapshot taken before each change of a not-yet-validated transaction (FR-076)."""

    transaction = models.ForeignKey(
        FinancialTransaction, on_delete=models.PROTECT, related_name="revisions"
    )
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField(encoder=DjangoJSONEncoder)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["revision"]

    def __str__(self) -> str:
        return f"{self.transaction_id} r{self.revision}"


class BudgetLine(FarmScopedModel, AuthoredModel, VersionedModel):
    campaign = models.ForeignKey(
        "production_plans.Campaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    plan_version = models.ForeignKey(
        "production_plans.PlanVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT, related_name="+")
    label = models.CharField(max_length=200)
    planned_amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    source_quote = models.ForeignKey(
        "irrigation.Quote", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_amount__gte=0), name="budget_planned_non_negative"
            )
        ]

    def __str__(self) -> str:
        return self.label


class BudgetAllocation(UUIDModel, TimestampedModel):
    """Explicit link between a transaction and a budget line (CLAUDE.md §11)."""

    transaction = models.ForeignKey(
        FinancialTransaction, on_delete=models.PROTECT, related_name="allocations"
    )
    budget_line = models.ForeignKey(
        BudgetLine, on_delete=models.PROTECT, related_name="allocations"
    )
    amount = models.DecimalField(**MONEY)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "budget_line"], name="budget_allocation_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="budget_allocation_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_id} → {self.budget_line_id}: {self.amount}"
