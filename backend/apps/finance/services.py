"""Treasury services (FR-070..077, OFFLINE_SYNC.md §7).

No "last write wins": a transaction is created once (idempotency key), may be
amended only while `submitted` (with a revision snapshot), and once validated
can only be reversed or corrected by new transactions.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.exceptions import (
    BusinessRuleError,
    IdentifierConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from apps.core.money import check_amount_precision, currency_exponent
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.farms.models import Farm
from apps.files.models import StoredFile
from apps.files.services import require_usable_file
from apps.finance.models import (
    BudgetAllocation,
    BudgetLine,
    FinanceCategory,
    FinancialTransaction,
    LedgerEntry,
    TransactionRevision,
    TreasuryAccount,
)
from apps.synchronization.services import flag_conflict, record_change

VIEW = "finance.view"
CREATE = "finance.transaction.create"
VALIDATE = "finance.transaction.validate"
ACCOUNTS = "finance.accounts.manage"
BUDGET = "finance.budget.edit"
TX_ENTITY = "finance.transaction"
ACCOUNT_ENTITY = "finance.account"
K = FinancialTransaction.Kind
ST = FinancialTransaction.Status
COUNTED = [ST.VALIDATED, ST.REVERSED]  # statuses whose entries make the balance
DUPLICATE_WINDOW = timedelta(hours=24)
MAX_FUTURE_DAYS = 1


def _event(ctx: TenantContext, action: str, tx: Any, **extra: Any) -> None:
    record_event(
        action=action,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type=TX_ENTITY,
        entity_id=tx.id,
        **extra,
    )


def _change(
    ctx: TenantContext, entity_type: str, instance: Any, origin_op_id: uuid.UUID | None = None
) -> None:
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=entity_type,
        entity_id=instance.id,
        entity_version=instance.version,
        required_permission=VIEW,
        origin_op_id=origin_op_id,
    )


def _farm(ctx: TenantContext) -> Farm:
    return Farm.objects.get(id=ctx.require_farm_id)


# --- Accounts and categories ------------------------------------------------------------


@transaction.atomic
def create_account(ctx: TenantContext, *, data: dict[str, Any]) -> TreasuryAccount:
    ctx.require(ACCOUNTS)
    currency_exponent(data["currency"])
    account = TreasuryAccount(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    account.full_clean(validate_unique=False, validate_constraints=False)
    try:
        with transaction.atomic():
            account.save()
    except IntegrityError as exc:
        raise BusinessRuleError(
            "Un compte porte déjà ce nom.", field_errors={"name": ["Déjà utilisé."]}
        ) from exc
    record_event(
        action="treasury_account.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type=ACCOUNT_ENTITY,
        entity_id=account.id,
        after={"name": account.name, "currency": account.currency},
    )
    _change(ctx, ACCOUNT_ENTITY, account)
    return account


@transaction.atomic
def update_account(
    ctx: TenantContext, *, account_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> TreasuryAccount:
    ctx.require(ACCOUNTS)
    account = (
        TreasuryAccount.objects.select_for_update()
        .filter(id=account_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if account is None:
        raise NotFoundError()
    check_version(account, expected_version)
    if (
        "currency" in changes
        and changes["currency"] != account.currency
        and account.entries.exists()
    ):
        raise BusinessRuleError("La devise d'un compte mouvementé ne peut pas changer.")
    diff = apply_changes(account, changes)
    if diff:
        account.version += 1
        account.updated_by = ctx.user
        account.save()
        record_event(
            action="treasury_account.updated",
            actor=ctx.user,
            organization_id=ctx.organization_id,
            farm_id=ctx.farm_id,
            entity_type=ACCOUNT_ENTITY,
            entity_id=account.id,
            after={k: v[1] for k, v in diff.items()},
        )
        _change(ctx, ACCOUNT_ENTITY, account)
    return account


@transaction.atomic
def create_category(ctx: TenantContext, *, data: dict[str, Any]) -> FinanceCategory:
    ctx.require(ACCOUNTS)
    parent = data.get("parent")
    if parent is not None and (
        parent.organization_id != ctx.organization_id or parent.kind != data["kind"]
    ):
        raise BusinessRuleError(
            "Catégorie parente incompatible.", field_errors={"parent": ["Invalide."]}
        )
    try:
        with transaction.atomic():
            return FinanceCategory.objects.create(organization_id=ctx.organization_id, **data)
    except IntegrityError as exc:
        raise BusinessRuleError(
            "Ce code de catégorie existe déjà.", field_errors={"code": ["Déjà utilisé."]}
        ) from exc


# --- Recording -------------------------------------------------------------------------


def _account(
    ctx: TenantContext, account: TreasuryAccount, field: str = "account"
) -> TreasuryAccount:
    locked = (
        TreasuryAccount.objects.select_for_update()
        .filter(id=account.id, farm_id=ctx.require_farm_id)
        .first()
    )
    if locked is None:
        raise BusinessRuleError("Compte introuvable.", field_errors={field: ["Introuvable."]})
    if not locked.is_active:
        raise BusinessRuleError(
            "Le compte est désactivé.",
            details={"reason": "account_inactive"},
            field_errors={field: ["Compte désactivé."]},
        )
    return locked


def _check_links(ctx: TenantContext, data: dict[str, Any]) -> None:
    for name in ("campaign", "plan", "crop_cycle"):
        obj = data.get(name)
        if obj is not None and obj.farm_id != ctx.farm_id:
            raise BusinessRuleError("Référence introuvable.", field_errors={name: ["Introuvable."]})
    counterparty = data.get("counterparty")
    if counterparty is not None and counterparty.organization_id != ctx.organization_id:
        raise BusinessRuleError(
            "Tiers introuvable.", field_errors={"counterparty": ["Introuvable."]}
        )


def _check_amount(amount: Decimal, currency: str) -> None:
    if amount <= 0:
        raise BusinessRuleError("Le montant doit être positif.", field_errors={"amount": ["> 0"]})
    check_amount_precision(amount, currency)


def _check_date(ctx: TenantContext, business_date: date) -> bool:
    """Return True when the date is back-dated beyond the farm limit (forces submission)."""
    today = timezone.localdate()
    if business_date > today + timedelta(days=MAX_FUTURE_DAYS):
        raise BusinessRuleError("Date dans le futur.", field_errors={"business_date": ["Future."]})
    limit = _farm(ctx).get_setting("backdate_limit_days")
    return business_date < today - timedelta(days=limit)


def _replay(
    ctx: TenantContext, key: uuid.UUID, tx_id: uuid.UUID | None, fingerprint: dict[str, Any]
) -> FinancialTransaction | None:
    existing = FinancialTransaction.objects.filter(
        Q(farm_id=ctx.require_farm_id, idempotency_key=key) | Q(id=tx_id or key)
    ).first()
    if existing is None:
        return None
    if existing.farm_id != ctx.farm_id:
        raise IdentifierConflictError("Identifiant déjà utilisé.")
    same = (
        existing.kind == fingerprint["kind"]
        and existing.amount == fingerprint["amount"]
        and existing.business_date == fingerprint["business_date"]
    )
    if not same:
        raise IdentifierConflictError(
            "Clé d'idempotence déjà utilisée pour une autre transaction.",
            details={"existing_id": str(existing.id)},
        )
    return existing


def _initial_status(ctx: TenantContext, *, backdated: bool, duplicate: bool) -> str:
    auto = _farm(ctx).get_setting("auto_validate_own_transactions")
    if auto and ctx.has_perm(VALIDATE) and not backdated and not duplicate:
        return ST.VALIDATED
    return ST.SUBMITTED


def _possible_duplicate(
    ctx: TenantContext, account: TreasuryAccount, data: dict[str, Any]
) -> FinancialTransaction | None:
    """Same account, kind, amount, date and category recorded recently by another
    author or device: accepted but never auto-validated (OFFLINE_SYNC.md §7)."""
    since = timezone.now() - DUPLICATE_WINDOW
    candidates = FinancialTransaction.objects.filter(
        farm_id=ctx.require_farm_id,
        kind=data["kind"],
        amount=data["amount"],
        business_date=data["business_date"],
        category=data.get("category"),
        entries__account=account,
        created_at__gte=since,
    ).exclude(status=ST.REJECTED)
    device = data.get("device")
    for candidate in candidates:
        if candidate.created_by_id != ctx.user.pk or (
            device and candidate.device_id and candidate.device_id != device.id
        ):
            return candidate
    return None


def _attach(ctx: TenantContext, tx: FinancialTransaction, attachments: list[Any]) -> None:
    for stored in attachments:
        tx.attachments.add(require_usable_file(ctx, stored.id, StoredFile.Purpose.RECEIPT))


@transaction.atomic
def record_transaction(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[FinancialTransaction, bool]:
    """Record an expense or an income. Returns (transaction, created)."""
    ctx.require(CREATE)
    data = dict(data)
    kind = data["kind"]
    if kind not in {K.EXPENSE, K.INCOME}:
        raise BusinessRuleError("Utiliser l'opération de transfert pour un transfert.")
    key = data.pop("idempotency_key")
    attachments = data.pop("attachments", [])
    existing = _replay(ctx, key, data.get("id"), data)
    if existing is not None:
        return existing, False
    account = _account(ctx, data.pop("account"))
    currency = data.setdefault("currency", account.currency)
    if currency != account.currency:
        raise BusinessRuleError(
            "La devise doit être celle du compte.",
            details={"reason": "currency_mismatch"},
            field_errors={"currency": [f"Attendu : {account.currency}."]},
        )
    _check_amount(data["amount"], currency)
    category = data.get("category")
    if (
        category is None
        or category.organization_id != ctx.organization_id
        or category.kind != kind
        or not category.is_active
    ):
        raise BusinessRuleError(
            "Catégorie invalide pour ce type d'opération.", field_errors={"category": ["Invalide."]}
        )
    _check_links(ctx, data)
    backdated = _check_date(ctx, data["business_date"])
    duplicate_of = _possible_duplicate(ctx, account, {**data, "kind": kind})
    status = _initial_status(ctx, backdated=backdated, duplicate=duplicate_of is not None)
    try:
        with transaction.atomic():
            tx = FinancialTransaction.objects.create(
                organization_id=ctx.organization_id,
                farm_id=ctx.require_farm_id,
                idempotency_key=key,
                status=status,
                possible_duplicate=duplicate_of is not None,
                created_offline=origin_op_id is not None,
                created_by=ctx.user,
                updated_by=ctx.user,
                validated_by=ctx.user if status == ST.VALIDATED else None,
                validated_at=timezone.now() if status == ST.VALIDATED else None,
                **data,
            )
    except IntegrityError:
        # Concurrent delivery of the same idempotency key: the other one won.
        existing = _replay(ctx, key, data.get("id"), {**data, "kind": kind})
        if existing is None:
            raise
        return existing, False
    sign = Decimal(-1) if kind == K.EXPENSE else Decimal(1)
    LedgerEntry.objects.create(
        transaction=tx, account=account, amount=sign * tx.amount, currency=currency
    )
    _attach(ctx, tx, attachments)
    if duplicate_of is not None:
        flag_conflict(
            ctx,
            entity_type=TX_ENTITY,
            entity_id=tx.id,
            conflict_type="possible_duplicate",
            message="Transaction semblable enregistrée récemment : à vérifier.",
            client_payload={"transaction": str(tx.id)},
            server_snapshot={"similar_transaction": str(duplicate_of.id)},
        )
    _event(
        ctx,
        f"transaction.{kind}.recorded",
        tx,
        after={
            "amount": str(tx.amount),
            "currency": currency,
            "status": status,
            "account": str(account.id),
            "possible_duplicate": tx.possible_duplicate,
        },
    )
    _change(ctx, TX_ENTITY, tx, origin_op_id)
    return tx, True


@transaction.atomic
def record_transfer(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[FinancialTransaction, bool]:
    """Transfer between two accounts: two entries, excluded from income/expense (FR-073)."""
    ctx.require(CREATE)
    data = dict(data)
    data.pop("kind", None)
    key = data.pop("idempotency_key")
    existing = _replay(ctx, key, data.get("id"), {**data, "kind": K.TRANSFER})
    if existing is not None:
        return existing, False
    source = data.pop("account")
    target = data.pop("to_account")
    if source.id == target.id:
        raise BusinessRuleError(
            "Comptes source et destination identiques.",
            field_errors={"to_account": ["Identique à la source."]},
        )
    # Lock in a stable order to avoid deadlocks between concurrent transfers.
    first, second = sorted([source, target], key=lambda a: str(a.id))
    locked = {a.id: _account(ctx, a) for a in (first, second)}
    source, target = locked[source.id], locked[target.id]
    if source.currency != target.currency:
        raise BusinessRuleError(
            "Transfert entre devises différentes non pris en charge.",
            details={"reason": "currency_mismatch"},
        )
    currency = data.setdefault("currency", source.currency)
    if currency != source.currency:
        raise BusinessRuleError(
            "La devise doit être celle des comptes.",
            field_errors={"currency": [f"Attendu : {source.currency}."]},
        )
    _check_amount(data["amount"], currency)
    backdated = _check_date(ctx, data["business_date"])
    status = _initial_status(ctx, backdated=backdated, duplicate=False)
    tx = FinancialTransaction.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        kind=K.TRANSFER,
        idempotency_key=key,
        status=status,
        created_offline=origin_op_id is not None,
        created_by=ctx.user,
        updated_by=ctx.user,
        validated_by=ctx.user if status == ST.VALIDATED else None,
        validated_at=timezone.now() if status == ST.VALIDATED else None,
        **data,
    )
    LedgerEntry.objects.bulk_create(
        [
            LedgerEntry(transaction=tx, account=source, amount=-tx.amount, currency=currency),
            LedgerEntry(transaction=tx, account=target, amount=tx.amount, currency=currency),
        ]
    )
    _event(
        ctx,
        "transaction.transfer.recorded",
        tx,
        after={"amount": str(tx.amount), "from": str(source.id), "to": str(target.id)},
    )
    _change(ctx, TX_ENTITY, tx, origin_op_id)
    return tx, True


@transaction.atomic
def record_opening(
    ctx: TenantContext,
    *,
    account: TreasuryAccount,
    balance: Decimal,
    business_date: date,
    idempotency_key: uuid.UUID,
) -> FinancialTransaction:
    """Opening balance of an account (may be negative, e.g. an overdraft)."""
    ctx.require(VALIDATE)
    account = _account(ctx, account)
    if balance == 0:
        raise BusinessRuleError("Un solde d'ouverture nul ne nécessite pas d'écriture.")
    check_amount_precision(abs(balance), account.currency)
    if FinancialTransaction.objects.filter(kind=K.OPENING, entries__account=account).exists():
        raise BusinessRuleError("Ce compte a déjà un solde d'ouverture.")
    tx = FinancialTransaction.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        kind=K.OPENING,
        status=ST.VALIDATED,
        business_date=business_date,
        amount=abs(balance),
        currency=account.currency,
        idempotency_key=idempotency_key,
        description="Solde d'ouverture",
        created_by=ctx.user,
        updated_by=ctx.user,
        validated_by=ctx.user,
        validated_at=timezone.now(),
    )
    LedgerEntry.objects.create(
        transaction=tx, account=account, amount=balance, currency=account.currency
    )
    _event(ctx, "transaction.opening.recorded", tx, after={"balance": str(balance)})
    _change(ctx, TX_ENTITY, tx)
    return tx


# --- Lifecycle ---------------------------------------------------------------------------


def _locked_tx(ctx: TenantContext, tx_id: Any) -> FinancialTransaction:
    tx = (
        FinancialTransaction.objects.select_for_update()
        .filter(id=tx_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if tx is None:
        raise NotFoundError()
    return tx


def _snapshot(tx: FinancialTransaction) -> dict[str, Any]:
    data = model_to_dict(tx, exclude=["attachments"])
    data["entries"] = [
        {"account": str(e.account_id), "amount": str(e.amount)} for e in tx.entries.all()
    ]
    return data


@transaction.atomic
def amend_transaction(
    ctx: TenantContext,
    *,
    tx_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    reason: str = "",
) -> FinancialTransaction:
    """Change a submitted (not yet validated) transaction, keeping a revision snapshot."""
    tx = _locked_tx(ctx, tx_id)
    check_version(tx, expected_version)
    if tx.status != ST.SUBMITTED:
        raise BusinessRuleError(
            "Une transaction validée n'est pas modifiable : annulez-la ou corrigez-la."
        )
    if tx.created_by_id != ctx.user.pk and not ctx.has_perm(VALIDATE):
        raise PermissionDeniedError(VALIDATE)
    allowed = {
        "amount",
        "business_date",
        "category",
        "description",
        "counterparty",
        "campaign",
        "plan",
        "crop_cycle",
    }
    if set(changes) - allowed:
        raise BusinessRuleError(
            "Champs non modifiables.",
            field_errors={n: ["Non modifiable."] for n in set(changes) - allowed},
        )
    _check_links(ctx, changes)
    if "amount" in changes:
        _check_amount(changes["amount"], tx.currency)
    if "category" in changes and (
        changes["category"] is None or changes["category"].kind != tx.kind
    ):
        raise BusinessRuleError("Catégorie invalide.", field_errors={"category": ["Invalide."]})
    if "business_date" in changes:
        _check_date(ctx, changes["business_date"])
    TransactionRevision.objects.create(
        transaction=tx,
        revision=tx.revision,
        snapshot=_snapshot(tx),
        changed_by=ctx.user,
        reason=reason,
    )
    diff = apply_changes(tx, changes)
    if "amount" in diff:
        for entry in tx.entries.all():
            entry.amount = tx.amount if entry.amount > 0 else -tx.amount
            entry.save(update_fields=["amount"])
    tx.revision += 1
    tx.version += 1
    tx.updated_by = ctx.user
    tx.save()
    _event(ctx, "transaction.amended", tx, after={k: str(v[1]) for k, v in diff.items()})
    _change(ctx, TX_ENTITY, tx)
    return tx


@transaction.atomic
def validate_transaction(
    ctx: TenantContext, *, tx_id: uuid.UUID, expected_version: int
) -> FinancialTransaction:
    ctx.require(VALIDATE)
    tx = _locked_tx(ctx, tx_id)
    check_version(tx, expected_version)
    if tx.status != ST.SUBMITTED:
        raise BusinessRuleError("Seule une transaction soumise peut être validée.")
    tx.status = ST.VALIDATED
    tx.validated_by = ctx.user
    tx.validated_at = timezone.now()
    tx.version += 1
    tx.save()
    _event(ctx, "transaction.validated", tx)
    _change(ctx, TX_ENTITY, tx)
    return tx


@transaction.atomic
def reject_transaction(
    ctx: TenantContext, *, tx_id: uuid.UUID, expected_version: int, reason: str
) -> FinancialTransaction:
    ctx.require(VALIDATE)
    tx = _locked_tx(ctx, tx_id)
    check_version(tx, expected_version)
    if tx.status != ST.SUBMITTED:
        raise BusinessRuleError("Seule une transaction soumise peut être rejetée.")
    if not reason.strip():
        raise BusinessRuleError("Motif obligatoire.", field_errors={"reason": ["Obligatoire."]})
    tx.status = ST.REJECTED
    tx.rejected_reason = reason
    tx.version += 1
    tx.save()
    _event(ctx, "transaction.rejected", tx, after={"reason": reason})
    _change(ctx, TX_ENTITY, tx)
    return tx


@transaction.atomic
def reverse_transaction(
    ctx: TenantContext,
    *,
    tx_id: uuid.UUID,
    reason: str,
    idempotency_key: uuid.UUID | None = None,
    origin_op_id: uuid.UUID | None = None,
) -> FinancialTransaction:
    """Cancel a validated transaction with an opposite, validated entry (FR-076)."""
    ctx.require(VALIDATE)
    tx = _locked_tx(ctx, tx_id)
    if tx.status == ST.REVERSED:
        return tx.reversal  # converge: already reversed
    if tx.status != ST.VALIDATED or tx.kind == K.REVERSAL:
        raise BusinessRuleError("Seule une transaction validée peut être annulée.")
    if not reason.strip():
        raise BusinessRuleError("Motif obligatoire.", field_errors={"reason": ["Obligatoire."]})
    reversal = FinancialTransaction.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        kind=K.REVERSAL,
        status=ST.VALIDATED,
        business_date=timezone.localdate(),
        amount=tx.amount,
        currency=tx.currency,
        category=tx.category,
        description=f"Annulation : {reason}",
        reverses=tx,
        idempotency_key=idempotency_key or uuid.uuid4(),
        campaign=tx.campaign,
        plan=tx.plan,
        crop_cycle=tx.crop_cycle,
        created_offline=origin_op_id is not None,
        created_by=ctx.user,
        updated_by=ctx.user,
        validated_by=ctx.user,
        validated_at=timezone.now(),
    )
    LedgerEntry.objects.bulk_create(
        [
            LedgerEntry(
                transaction=reversal, account_id=e.account_id, amount=-e.amount, currency=e.currency
            )
            for e in tx.entries.all()
        ]
    )
    tx.status = ST.REVERSED
    tx.version += 1
    tx.save(update_fields=["status", "version", "updated_at"])
    _event(ctx, "transaction.reversed", tx, after={"reversal": str(reversal.id), "reason": reason})
    _change(ctx, TX_ENTITY, tx, origin_op_id)
    _change(ctx, TX_ENTITY, reversal, origin_op_id)
    return reversal


@transaction.atomic
def correct_transaction(
    ctx: TenantContext, *, tx_id: uuid.UUID, reason: str, corrected: dict[str, Any]
) -> FinancialTransaction:
    """Correction = reversal of the original + new transaction linked to it."""
    original = _locked_tx(ctx, tx_id)
    if original.kind not in {K.EXPENSE, K.INCOME}:
        raise BusinessRuleError("Seules les dépenses et recettes se corrigent ainsi.")
    reverse_transaction(ctx, tx_id=original.id, reason=reason)
    entry = original.entries.get()
    data = {
        "kind": original.kind,
        "account": entry.account,
        "category": original.category,
        "business_date": original.business_date,
        "description": original.description,
        "counterparty": original.counterparty,
        "campaign": original.campaign,
        "plan": original.plan,
        "crop_cycle": original.crop_cycle,
        "idempotency_key": uuid.uuid4(),
        **corrected,
    }
    new_tx, _ = record_transaction(ctx, data=data)
    new_tx.corrects = original
    new_tx.save(update_fields=["corrects"])
    _event(ctx, "transaction.corrected", original, after={"correction": str(new_tx.id)})
    return new_tx


def sync_reverse(
    ctx: TenantContext,
    *,
    entity_id: uuid.UUID,
    payload: dict[str, Any],
    base_version: int | None,
    origin_op_id: uuid.UUID,
) -> dict[str, Any]:
    reversal = reverse_transaction(
        ctx,
        tx_id=entity_id,
        reason=payload.get("reason", ""),
        idempotency_key=origin_op_id,
        origin_op_id=origin_op_id,
    )
    return {
        "entity_version": FinancialTransaction.objects.get(id=entity_id).version,
        "reversal_id": str(reversal.id),
    }


def sync_create(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[FinancialTransaction, bool]:
    """Offline creation: the client transaction id is the idempotency key."""
    data = {**data, "idempotency_key": data["id"]}
    if data["kind"] == K.TRANSFER:
        return record_transfer(ctx, data=data, origin_op_id=origin_op_id)
    data.pop("to_account", None)
    return record_transaction(ctx, data=data, origin_op_id=origin_op_id)


# --- Balances, treasury, budgets ----------------------------------------------------------


def account_balances(ctx: TenantContext, *, as_of: date | None = None) -> list[dict[str, Any]]:
    """Balance = Σ entries of validated/reversed transactions (FR-074).

    The provisional balance also includes submitted transactions and is labelled as such.
    """
    ctx.require(VIEW)
    rows = []
    for account in TreasuryAccount.objects.filter(farm_id=ctx.require_farm_id).order_by("name"):
        entries = account.entries.all()
        if as_of is not None:
            entries = entries.filter(transaction__business_date__lte=as_of)
        validated = entries.filter(transaction__status__in=COUNTED).aggregate(s=Sum("amount"))[
            "s"
        ] or Decimal(0)
        pending = entries.filter(transaction__status=ST.SUBMITTED).aggregate(s=Sum("amount"))[
            "s"
        ] or Decimal(0)
        rows.append(
            {
                "account": str(account.id),
                "name": account.name,
                "currency": account.currency,
                "balance": validated,
                "pending": pending,
                "provisional_balance": validated + pending,
                "is_active": account.is_active,
            }
        )
    return rows


def _bucket(day: date, period: str) -> date:
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    raise BusinessRuleError("Période inconnue (day, week, month).")


def treasury(ctx: TenantContext, *, period: str, date_from: date, date_to: date) -> dict[str, Any]:
    """Inflows, outflows and closing balances per period and currency (FR-077).

    Transfers move money between accounts and are excluded from inflows/outflows;
    a reversal reduces the flow of the transaction it cancels.
    """
    ctx.require(VIEW)
    if date_to < date_from:
        raise BusinessRuleError("Période invalide.")
    entries = LedgerEntry.objects.filter(
        transaction__farm_id=ctx.require_farm_id,
        transaction__status__in=COUNTED,
    ).select_related("transaction", "transaction__reverses")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        tx = entry.transaction
        currency = entry.currency
        per_currency = result.setdefault(currency, {"opening": Decimal(0), "buckets": {}})
        if tx.business_date < date_from:
            per_currency["opening"] += entry.amount
            continue
        if tx.business_date > date_to:
            continue
        key = _bucket(tx.business_date, period).isoformat()
        bucket = per_currency["buckets"].setdefault(
            key,
            {
                "inflows": Decimal(0),
                "outflows": Decimal(0),
                "transfers": Decimal(0),
                "opening_entries": Decimal(0),
                "net": Decimal(0),
            },
        )
        kind = tx.reverses.kind if tx.kind == K.REVERSAL and tx.reverses else tx.kind
        if kind == K.INCOME:
            bucket["inflows"] += entry.amount
        elif kind == K.EXPENSE:
            bucket["outflows"] += -entry.amount
        elif kind == K.TRANSFER:
            bucket["transfers"] += abs(entry.amount) / 2  # both legs of the transfer
        elif kind == K.OPENING:
            bucket["opening_entries"] += entry.amount
        bucket["net"] += entry.amount
    output = {}
    for currency, data in result.items():
        running = data["opening"]
        periods = []
        for key in sorted(data["buckets"]):
            bucket = data["buckets"][key]
            running += bucket["net"]
            periods.append({"period_start": key, **bucket, "closing_balance": running})
        output[currency] = {"opening_balance": data["opening"], "periods": periods}
    return {"period": period, "date_from": date_from, "date_to": date_to, "currencies": output}


@transaction.atomic
def create_budget_line(ctx: TenantContext, *, data: dict[str, Any]) -> BudgetLine:
    ctx.require(BUDGET)
    category = data["category"]
    if category.organization_id != ctx.organization_id:
        raise BusinessRuleError(
            "Catégorie introuvable.", field_errors={"category": ["Introuvable."]}
        )
    currency_exponent(data["currency"])
    check_amount_precision(data["planned_amount"], data["currency"], "planned_amount")
    for name in ("campaign", "plan_version", "source_quote"):
        obj = data.get(name)
        if obj is not None and obj.farm_id != ctx.farm_id:
            raise BusinessRuleError("Référence introuvable.", field_errors={name: ["Introuvable."]})
    line = BudgetLine.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    record_event(
        action="budget_line.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type="finance.budget_line",
        entity_id=line.id,
        after={"amount": str(line.planned_amount), "label": line.label},
    )
    return line


@transaction.atomic
def budget_line_from_quote(
    ctx: TenantContext, *, quote: Any, category: FinanceCategory, label: str = ""
) -> BudgetLine:
    if quote.farm_id != ctx.farm_id:
        raise NotFoundError()
    if quote.status not in {"issued", "accepted"}:
        raise BusinessRuleError("Seul un devis émis ou accepté peut alimenter le budget.")
    return create_budget_line(
        ctx,
        data={
            "category": category,
            "label": label or f"Devis n°{quote.number}",
            "planned_amount": quote.total,
            "currency": quote.currency,
            "source_quote": quote,
            "plan_version": quote.design.plan_version,
        },
    )


@transaction.atomic
def allocate(
    ctx: TenantContext, *, tx_id: uuid.UUID, budget_line_id: uuid.UUID, amount: Decimal
) -> BudgetAllocation:
    """Explicit link transaction → budget line; total allocated ≤ transaction amount."""
    ctx.require(BUDGET)
    tx = _locked_tx(ctx, tx_id)
    if tx.kind != K.EXPENSE or tx.status not in {ST.SUBMITTED, ST.VALIDATED}:
        raise BusinessRuleError("Seule une dépense soumise ou validée peut être ventilée.")
    line = BudgetLine.objects.filter(id=budget_line_id, farm_id=ctx.require_farm_id).first()
    if line is None:
        raise BusinessRuleError(
            "Ligne budgétaire introuvable.", field_errors={"budget_line": ["Introuvable."]}
        )
    if line.currency != tx.currency:
        raise BusinessRuleError("Devise différente de la ligne budgétaire.")
    _check_amount(amount, tx.currency)
    already = tx.allocations.exclude(budget_line=line).aggregate(s=Sum("amount"))["s"] or 0
    if already + amount > tx.amount:
        raise BusinessRuleError(
            "Le total ventilé dépasse le montant de la transaction.",
            details={"available": str(tx.amount - already)},
        )
    allocation, _ = BudgetAllocation.objects.update_or_create(
        transaction=tx, budget_line=line, defaults={"amount": amount, "created_by": ctx.user}
    )
    _event(
        ctx, "transaction.allocated", tx, after={"budget_line": str(line.id), "amount": str(amount)}
    )
    return allocation


def budget_report(
    ctx: TenantContext, *, campaign_id: Any = None, plan_version_id: Any = None
) -> list[dict[str, Any]]:
    """Planned vs actual per budget line (FR-075); actual = validated allocations only."""
    ctx.require(VIEW)
    lines = BudgetLine.objects.filter(farm_id=ctx.require_farm_id).select_related("category")
    if campaign_id:
        lines = lines.filter(campaign_id=campaign_id)
    if plan_version_id:
        lines = lines.filter(plan_version_id=plan_version_id)
    report = []
    for line in lines.order_by("label"):
        actual = line.allocations.filter(transaction__status=ST.VALIDATED).aggregate(
            s=Sum("amount")
        )["s"] or Decimal(0)
        pending = line.allocations.filter(transaction__status=ST.SUBMITTED).aggregate(
            s=Sum("amount")
        )["s"] or Decimal(0)
        variance = actual - line.planned_amount
        pct = (
            (variance / line.planned_amount * 100).quantize(Decimal("0.01"))
            if line.planned_amount
            else None
        )
        report.append(
            {
                "budget_line": str(line.id),
                "label": line.label,
                "category": line.category.name,
                "currency": line.currency,
                "planned": line.planned_amount,
                "actual": actual,
                "pending": pending,
                "variance": variance,
                "variance_pct": pct,
            }
        )
    return report
