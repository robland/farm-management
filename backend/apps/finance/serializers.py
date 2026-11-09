from typing import Any

from rest_framework import serializers

from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.files.models import StoredFile
from apps.finance.models import (
    BudgetLine,
    FinanceCategory,
    FinancialTransaction,
    LedgerEntry,
    Loan,
    TreasuryAccount,
)
from apps.inventory.models import Supplier
from apps.inventory.serializers import OrgScopedRelatedField
from apps.irrigation.models import Quote
from apps.production_plans.models import Campaign, CropCycle, PlanVersion, ProductionPlan

MONEY: dict[str, Any] = {"max_digits": 19, "decimal_places": 4}


class TreasuryAccountSerializer(serializers.ModelSerializer):
    # Main or operating at creation (the first account of a farm is its main account);
    # member accounts are opened by their holder (`accounts/mine/`), Q35.
    role = serializers.ChoiceField(
        choices=[TreasuryAccount.Role.MAIN, TreasuryAccount.Role.OPERATING], required=False
    )

    class Meta:
        model = TreasuryAccount
        fields = [
            "id",
            "name",
            "kind",
            "role",
            "holder",
            "currency",
            "institution",
            "account_ref",
            "is_active",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "holder", "version", "created_at"]


class MemberAccountOpenSerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=3, required=False)
    kind = serializers.ChoiceField(choices=TreasuryAccount.Kind.choices, required=False)


class FinanceCategorySerializer(serializers.ModelSerializer):
    # Exposed as `parent_category`: `parent` is reserved by DRF fields.
    parent_category = OrgScopedRelatedField(
        source="parent", queryset=FinanceCategory.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = FinanceCategory
        fields = [
            "id",
            "kind",
            "code",
            "name",
            "parent_category",
            "is_capex",
            "is_active",
            "version",
        ]
        read_only_fields = ["id", "version"]
        validators: list[Any] = []


class LoanSerializer(serializers.ModelSerializer):
    counterparty = OrgScopedRelatedField(
        queryset=Supplier.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Loan
        fields = [
            "id",
            "lender",
            "counterparty",
            "principal",
            "currency",
            "started_on",
            "notes",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "version", "created_at"]


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["account", "amount", "currency"]
        read_only_fields = fields


class TransactionSerializer(serializers.ModelSerializer):
    """Read representation (also used by the sync pull)."""

    entries = LedgerEntrySerializer(many=True, read_only=True)

    class Meta:
        model = FinancialTransaction
        fields = [
            "id",
            "kind",
            "status",
            "business_date",
            "amount",
            "currency",
            "category",
            "description",
            "counterparty",
            "campaign",
            "plan",
            "crop_cycle",
            "reverses",
            "corrects",
            "loan",
            "possible_duplicate",
            "created_offline",
            "validated_by",
            "validated_at",
            "rejected_reason",
            "revision",
            "attachments",
            "entries",
            "created_by",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TransactionInputSerializer(serializers.Serializer):
    """Creation of an expense, income, transfer, funding or repayment (REST and sync)."""

    id = serializers.UUIDField(required=False)
    kind = serializers.ChoiceField(
        choices=["expense", "income", "transfer", "funding", "repayment"]
    )
    business_date = serializers.DateField()
    amount = serializers.DecimalField(**MONEY)
    currency = serializers.CharField(max_length=3, required=False)
    account = FarmScopedPrimaryKeyRelatedField(queryset=TreasuryAccount.objects.all())
    to_account = FarmScopedPrimaryKeyRelatedField(
        queryset=TreasuryAccount.objects.all(), required=False, allow_null=True
    )
    category = OrgScopedRelatedField(
        queryset=FinanceCategory.objects.all(), required=False, allow_null=True
    )
    description = serializers.CharField(required=False, allow_blank=True)
    counterparty = OrgScopedRelatedField(
        queryset=Supplier.objects.all(), required=False, allow_null=True
    )
    campaign = FarmScopedPrimaryKeyRelatedField(
        queryset=Campaign.objects.all(), required=False, allow_null=True
    )
    plan = FarmScopedPrimaryKeyRelatedField(
        queryset=ProductionPlan.objects.all(), required=False, allow_null=True
    )
    crop_cycle = FarmScopedPrimaryKeyRelatedField(
        queryset=CropCycle.objects.all(), required=False, allow_null=True
    )
    loan = FarmScopedPrimaryKeyRelatedField(
        queryset=Loan.objects.all(), required=False, allow_null=True
    )
    attachments = OrgScopedRelatedField(
        queryset=StoredFile.objects.all(), many=True, required=False
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        kind = attrs["kind"]
        if kind == "transfer":
            # Without `to_account`, a member account is transferred to the main account,
            # which a contributor cannot see (checked by the service).
            for name in ("category", "counterparty", "loan"):
                if attrs.get(name):
                    raise serializers.ValidationError({name: ["Interdit pour un transfert."]})
        elif kind == "repayment":
            if not attrs.get("loan"):
                raise serializers.ValidationError({"loan": ["Obligatoire."]})
            if attrs.get("category"):
                raise serializers.ValidationError(
                    {"category": ["Le capital remboursé n'est pas une dépense."]}
                )
        elif not attrs.get("category"):
            raise serializers.ValidationError({"category": ["Obligatoire."]})
        elif kind in ("expense", "income") and attrs.get("loan"):
            raise serializers.ValidationError({"loan": ["Réservé aux apports et remboursements."]})
        return attrs


class AmendSerializer(serializers.Serializer):
    amount = serializers.DecimalField(**MONEY, required=False)
    business_date = serializers.DateField(required=False)
    category = OrgScopedRelatedField(queryset=FinanceCategory.objects.all(), required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField()


class CorrectionSerializer(serializers.Serializer):
    reason = serializers.CharField()
    amount = serializers.DecimalField(**MONEY, required=False)
    business_date = serializers.DateField(required=False)
    category = OrgScopedRelatedField(queryset=FinanceCategory.objects.all(), required=False)
    description = serializers.CharField(required=False, allow_blank=True)


class OpeningSerializer(serializers.Serializer):
    account = FarmScopedPrimaryKeyRelatedField(queryset=TreasuryAccount.objects.all())
    balance = serializers.DecimalField(**MONEY)
    business_date = serializers.DateField()


class TreasuryQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=["day", "week", "month"], default="month")
    date_from = serializers.DateField()
    date_to = serializers.DateField()


class BalanceQuerySerializer(serializers.Serializer):
    as_of = serializers.DateField(required=False)


class BudgetLineSerializer(serializers.ModelSerializer):
    category = OrgScopedRelatedField(queryset=FinanceCategory.objects.all())
    campaign = FarmScopedPrimaryKeyRelatedField(
        queryset=Campaign.objects.all(), required=False, allow_null=True
    )
    plan_version = FarmScopedPrimaryKeyRelatedField(
        queryset=PlanVersion.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = BudgetLine
        fields = [
            "id",
            "campaign",
            "plan_version",
            "category",
            "label",
            "planned_amount",
            "currency",
            "source_quote",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "source_quote", "version", "created_at"]


class BudgetFromQuoteSerializer(serializers.Serializer):
    quote = FarmScopedPrimaryKeyRelatedField(queryset=Quote.objects.all())
    category = OrgScopedRelatedField(queryset=FinanceCategory.objects.all())
    # Exposed as `title`: `label` is reserved by DRF fields.
    title = serializers.CharField(source="label", required=False, allow_blank=True)


class AllocationSerializer(serializers.Serializer):
    budget_line = serializers.UUIDField()
    amount = serializers.DecimalField(**MONEY)


class BudgetReportQuerySerializer(serializers.Serializer):
    campaign = serializers.UUIDField(required=False)
    plan_version = serializers.UUIDField(required=False)
