import uuid
from typing import Any

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.money import check_amount_precision, currency_exponent
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.inventory.models import PriceList, PriceListItem

VIEW = "inventory.view"
EDIT = "inventory.edit"


def _event(ctx: TenantContext, action: str, instance: Any, **extra: Any) -> None:
    record_event(
        action=f"{type(instance).__name__.lower()}.{action}",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type=f"inventory.{type(instance).__name__.lower()}",
        entity_id=instance.pk,
        **extra,
    )


def _save(instance: models.Model, message: str, field: str = "name") -> None:
    try:
        with transaction.atomic():
            instance.full_clean(validate_unique=False, validate_constraints=False)
            instance.save()
    except IntegrityError as exc:
        raise BusinessRuleError(message, field_errors={field: ["Déjà utilisé."]}) from exc


@transaction.atomic
def create_org_object(ctx: TenantContext, model: type[Any], data: dict[str, Any]) -> Any:
    ctx.require(EDIT)
    instance = model(
        organization_id=ctx.organization_id, created_by=ctx.user, updated_by=ctx.user, **data
    )
    _save(instance, "Cet élément existe déjà.")
    _event(ctx, "created", instance)
    return instance


def _locked(ctx: TenantContext, model: type[Any], pk: uuid.UUID) -> Any:
    queryset = model.objects.select_for_update().filter(id=pk, organization_id=ctx.organization_id)
    if hasattr(model, "deleted_at"):
        queryset = queryset.filter(deleted_at__isnull=True)
    instance = queryset.first()
    if instance is None:
        raise NotFoundError()
    return instance


@transaction.atomic
def update_org_object(
    ctx: TenantContext,
    model: type[Any],
    pk: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
) -> Any:
    ctx.require(EDIT)
    instance = _locked(ctx, model, pk)
    check_version(instance, expected_version)
    if (
        isinstance(instance, PriceList)
        and instance.status != PriceList.Status.DRAFT
        and set(changes) - {"status", "valid_to", "notes"}
    ):
        raise BusinessRuleError("Une liste de prix active n'est plus modifiable.")
    diff = apply_changes(instance, changes)
    if diff:
        instance.version += 1
        instance.updated_by = ctx.user
        _save(instance, "Cet élément existe déjà.")
        _event(
            ctx, "updated", instance, after={k: getattr(v[1], "pk", v[1]) for k, v in diff.items()}
        )
    return instance


@transaction.atomic
def delete_org_object(
    ctx: TenantContext, model: type[Any], pk: uuid.UUID, expected_version: int
) -> None:
    ctx.require(EDIT)
    instance = _locked(ctx, model, pk)
    check_version(instance, expected_version)
    instance.deleted_at = timezone.now()
    instance.deleted_by = ctx.user
    instance.version += 1
    instance.save()
    _event(ctx, "deleted", instance)


@transaction.atomic
def create_price_list(ctx: TenantContext, data: dict[str, Any]) -> PriceList:
    currency_exponent(data["currency"])  # rejects unsupported currencies
    supplier = data["supplier"]
    if supplier.organization_id != ctx.organization_id or supplier.deleted_at is not None:
        raise BusinessRuleError(
            "Fournisseur introuvable.", field_errors={"supplier": ["Introuvable."]}
        )
    price_list: PriceList = create_org_object(ctx, PriceList, data)
    return price_list


@transaction.atomic
def set_price_items(
    ctx: TenantContext,
    *,
    price_list_id: uuid.UUID,
    expected_version: int,
    items: list[dict[str, Any]],
) -> PriceList:
    ctx.require(EDIT)
    price_list = _locked(ctx, PriceList, price_list_id)
    check_version(price_list, expected_version)
    if price_list.status != PriceList.Status.DRAFT:
        raise BusinessRuleError(
            "Une liste de prix active n'est plus modifiable : créez une nouvelle liste."
        )
    rows = []
    for index, item in enumerate(items):
        if item["catalog_item"].organization_id != ctx.organization_id:
            raise BusinessRuleError(
                "Article introuvable.",
                field_errors={f"items.{index}.catalog_item": ["Introuvable."]},
            )
        check_amount_precision(item["unit_price"], price_list.currency, f"items.{index}.unit_price")
        rows.append(PriceListItem(price_list=price_list, **item))
    price_list.items.all().delete()
    try:
        with transaction.atomic():
            PriceListItem.objects.bulk_create(rows)
    except IntegrityError as exc:
        raise BusinessRuleError("Article en double dans la liste.") from exc
    price_list.version += 1
    price_list.save()
    _event(ctx, "items_set", price_list, after={"count": len(rows)})
    return price_list
