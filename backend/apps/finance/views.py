import uuid
from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import PreconditionRequiredError
from apps.core.versioning import parse_if_match
from apps.core.viewsets import CHECKED_IN_SERVICE
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.finance import services
from apps.finance.models import (
    BudgetLine,
    FinanceCategory,
    FinancialTransaction,
    Loan,
    TreasuryAccount,
)
from apps.finance.serializers import (
    AllocationSerializer,
    AmendSerializer,
    BalanceQuerySerializer,
    BudgetFromQuoteSerializer,
    BudgetLineSerializer,
    BudgetReportQuerySerializer,
    CorrectionSerializer,
    FinanceCategorySerializer,
    LoanSerializer,
    MemberAccountOpenSerializer,
    OpeningSerializer,
    ReasonSerializer,
    TransactionInputSerializer,
    TransactionSerializer,
    TreasuryAccountSerializer,
    TreasuryQuerySerializer,
)
from apps.organizations.viewsets import OrgScopedGenericViewSet

V = services.VIEW


def idempotency_key(request: Request) -> uuid.UUID:
    """Financial creations require an `Idempotency-Key` header (ARCHITECTURE.md §2.3)."""
    raw = request.headers.get("Idempotency-Key", "")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise PreconditionRequiredError("En-tête Idempotency-Key (UUID) obligatoire.") from exc


class TreasuryAccountViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = TreasuryAccountSerializer
    queryset = TreasuryAccount.objects.none()  # model hint for OpenAPI; see get_queryset
    http_method_names = ["get", "post", "patch", "head", "options"]
    # Reading: every account with finance.view, own member accounts with the funding
    # permission only (services.visible_accounts, Q35).
    permission_map = {
        "list": CHECKED_IN_SERVICE,
        "retrieve": CHECKED_IN_SERVICE,
        "create": services.ACCOUNTS,
        "partial_update": services.ACCOUNTS,
        "balances": CHECKED_IN_SERVICE,
        "members": CHECKED_IN_SERVICE,
        "mine": services.FUND,
        "set_main": services.ACCOUNTS,
        "opening": services.VALIDATE,
    }

    def get_queryset(self) -> QuerySet[TreasuryAccount]:
        return services.visible_accounts(self.tenant)

    @extend_schema(request=MemberAccountOpenSerializer, responses=TreasuryAccountSerializer)
    @action(detail=False, methods=["post"])
    def mine(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Open (or return) the current user's member account."""
        serializer = MemberAccountOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account, created = services.open_member_account(self.tenant, **serializer.validated_data)
        return Response(
            self.get_serializer(account).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(request=None, responses=TreasuryAccountSerializer)
    @action(detail=True, methods=["post"], url_path="set-main")
    def set_main(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account = services.set_main_account(self.tenant, account_id=self.get_object().id)
        return Response(self.get_serializer(account).data)

    @action(detail=False, methods=["get"])
    def members(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Contributions, transfers to the treasury and balance of each member account."""
        return Response(services.member_statement(self.tenant))

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.create_account(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(account).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account = self.get_object()
        serializer = self.get_serializer(account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        account = services.update_account(
            self.tenant,
            account_id=account.id,
            expected_version=parse_if_match(request),
            changes=dict(serializer.validated_data),
        )
        return Response(self.get_serializer(account).data)

    @extend_schema(parameters=[BalanceQuerySerializer])
    @action(detail=False, methods=["get"])
    def balances(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = BalanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            services.account_balances(self.tenant, as_of=query.validated_data.get("as_of"))
        )

    @extend_schema(
        request=OpeningSerializer,
        responses={201: TransactionSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", location="header", required=True)],
    )
    @action(detail=False, methods=["post"])
    def opening(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = OpeningSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        tx = services.record_opening(
            self.tenant, idempotency_key=idempotency_key(request), **serializer.validated_data
        )
        return Response(TransactionSerializer(tx).data, status=status.HTTP_201_CREATED)


class FinanceCategoryViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet
):
    serializer_class = FinanceCategorySerializer
    permission_map = {"list": V, "retrieve": V, "create": services.ACCOUNTS}
    filterset_fields = ["kind", "is_active"]

    def get_queryset(self) -> QuerySet[FinanceCategory]:
        return FinanceCategory.objects.filter(organization_id=self.tenant.organization_id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(category).data, status=status.HTTP_201_CREATED)


class TransactionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = TransactionSerializer
    queryset = FinancialTransaction.objects.none()  # model hint for OpenAPI; see get_queryset
    http_method_names = ["get", "post", "patch", "head", "options"]
    # Reading and recording are checked by the services: a contributor sees and records
    # only the movements of their own member account (Q35).
    permission_map = {
        "list": CHECKED_IN_SERVICE,
        "retrieve": CHECKED_IN_SERVICE,
        "create": CHECKED_IN_SERVICE,
        "partial_update": CHECKED_IN_SERVICE,
        "validate": services.VALIDATE,
        "reject": services.VALIDATE,
        "reverse": services.VALIDATE,
        "correct": services.VALIDATE,
        "allocate": services.BUDGET,
        "treasury": V,
        "revisions": V,
    }
    filterset_fields = [
        "kind",
        "status",
        "campaign",
        "plan",
        "category",
        "loan",
        "possible_duplicate",
    ]

    def get_queryset(self) -> QuerySet[FinancialTransaction]:
        queryset = services.visible_transactions(self.tenant).prefetch_related(
            "entries", "attachments"
        )
        account = self.request.query_params.get("account")
        if account:
            try:
                account_id = uuid.UUID(account)
            except ValueError:
                return queryset.none()
            queryset = queryset.filter(entries__account_id=account_id).distinct()
        return queryset

    def _fresh(self, pk: Any) -> Any:
        return TransactionSerializer(self.get_queryset().get(id=pk)).data

    @extend_schema(
        request=TransactionInputSerializer,
        responses={201: TransactionSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", location="header", required=True)],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        key = idempotency_key(request)
        serializer = TransactionInputSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = {**serializer.validated_data, "idempotency_key": key}
        recorder = {
            "transfer": services.record_transfer,
            "funding": services.record_funding,
            "repayment": services.record_repayment,
        }.get(data["kind"])
        if recorder is not None:
            tx, created = recorder(self.tenant, data=data)
        else:
            data.pop("to_account", None)
            tx, created = services.record_transaction(self.tenant, data=data)
        return Response(
            self._fresh(tx.id), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    @extend_schema(request=AmendSerializer, responses=TransactionSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AmendSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        reason = changes.pop("reason", "")
        tx = services.amend_transaction(
            self.tenant,
            tx_id=self.get_object().id,
            expected_version=parse_if_match(request),
            changes=changes,
            reason=reason,
        )
        return Response(self._fresh(tx.id))

    @extend_schema(request=None, responses=TransactionSerializer)
    @action(detail=True, methods=["post"])
    def validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        tx = services.validate_transaction(
            self.tenant, tx_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(self._fresh(tx.id))

    @extend_schema(request=ReasonSerializer, responses=TransactionSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx = services.reject_transaction(
            self.tenant,
            tx_id=self.get_object().id,
            expected_version=parse_if_match(request),
            reason=serializer.validated_data["reason"],
        )
        return Response(self._fresh(tx.id))

    @extend_schema(request=ReasonSerializer, responses={201: TransactionSerializer})
    @action(detail=True, methods=["post"])
    def reverse(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reversal = services.reverse_transaction(
            self.tenant, tx_id=self.get_object().id, reason=serializer.validated_data["reason"]
        )
        return Response(self._fresh(reversal.id), status=status.HTTP_201_CREATED)

    @extend_schema(request=CorrectionSerializer, responses={201: TransactionSerializer})
    @action(detail=True, methods=["post"])
    def correct(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CorrectionSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        new_tx = services.correct_transaction(
            self.tenant, tx_id=self.get_object().id, reason=reason, corrected=data
        )
        return Response(self._fresh(new_tx.id), status=status.HTTP_201_CREATED)

    @extend_schema(request=AllocationSerializer)
    @action(detail=True, methods=["post"])
    def allocate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AllocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocation = services.allocate(
            self.tenant,
            tx_id=self.get_object().id,
            budget_line_id=serializer.validated_data["budget_line"],
            amount=serializer.validated_data["amount"],
        )
        return Response(
            {
                "transaction": str(allocation.transaction_id),
                "budget_line": str(allocation.budget_line_id),
                "amount": str(allocation.amount),
            }
        )

    @action(detail=True, methods=["get"])
    def revisions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        tx = self.get_object()
        return Response(
            [
                {
                    "revision": r.revision,
                    "snapshot": r.snapshot,
                    "changed_by": str(r.changed_by_id),
                    "changed_at": r.changed_at,
                    "reason": r.reason,
                }
                for r in tx.revisions.all()
            ]
        )

    @extend_schema(parameters=[TreasuryQuerySerializer])
    @action(detail=False, methods=["get"])
    def treasury(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = TreasuryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(services.treasury(self.tenant, **query.validated_data))


class LoanViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    """Loans: disbursed by fundings, paid back by repayments (transactions, Q35)."""

    serializer_class = LoanSerializer
    permission_map = {
        "list": V,
        "retrieve": V,
        "create": services.ACCOUNTS,
        "positions": V,
    }

    def get_queryset(self) -> QuerySet[Loan]:
        return Loan.objects.filter(farm_id=self.farm_id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = services.create_loan(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(loan).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def positions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Disbursed, repaid and outstanding principal of each loan."""
        return Response(services.loans_report(self.tenant))


class BudgetLineViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = BudgetLineSerializer
    permission_map = {
        "list": V,
        "retrieve": V,
        "create": services.BUDGET,
        "from_quote": services.BUDGET,
        "report": V,
    }
    filterset_fields = ["campaign", "plan_version", "category"]

    def get_queryset(self) -> QuerySet[BudgetLine]:
        return BudgetLine.objects.filter(farm_id=self.farm_id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        line = services.create_budget_line(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(line).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=BudgetFromQuoteSerializer, responses={201: BudgetLineSerializer})
    @action(detail=False, methods=["post"], url_path="from-quote")
    def from_quote(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = BudgetFromQuoteSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        line = services.budget_line_from_quote(self.tenant, **serializer.validated_data)
        return Response(self.get_serializer(line).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[BudgetReportQuerySerializer])
    @action(detail=False, methods=["get"])
    def report(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = BudgetReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            services.budget_report(
                self.tenant,
                campaign_id=query.validated_data.get("campaign"),
                plan_version_id=query.validated_data.get("plan_version"),
            )
        )
