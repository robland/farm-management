from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin import ReadOnlyTabularInline
from apps.core.admin_services import ServiceAdmin, platform_context, service_action
from apps.core.tenancy import TenantContext
from apps.irrigation import services
from apps.irrigation.models import BomLine, IrrigationDesign, Quote, QuoteLine

DESIGN_FIELDS = ["parcel", "plan_version", "name", "system_type", "parameters", "bom_parameters"]


class BomLineInline(ReadOnlyTabularInline):
    model = BomLine


@admin.register(IrrigationDesign)
class IrrigationDesignAdmin(ServiceAdmin):
    """Design workflow: parameters → compute (hydraulics, bill of materials) → validate."""

    add_fields = DESIGN_FIELDS
    change_fields = DESIGN_FIELDS
    inlines = [BomLineInline]
    actions = ["compute", "validate", "new_version"]

    def can_change(self, obj: Any) -> bool:
        return obj.status == IrrigationDesign.Status.DRAFT

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> IrrigationDesign:
        return services.create_design(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_design(
            ctx, design_id=obj.id, expected_version=expected_version, changes=changes
        )

    @service_action("Calculer (débits, pertes de charge, nomenclature)")
    def compute(self, ctx: TenantContext, obj: IrrigationDesign) -> None:
        services.compute_design(ctx, design_id=obj.id)

    @service_action("Valider la conception")
    def validate(self, ctx: TenantContext, obj: IrrigationDesign) -> None:
        services.validate_design(ctx, design_id=obj.id, expected_version=obj.version)

    @service_action("Créer une nouvelle version (brouillon)")
    def new_version(self, ctx: TenantContext, obj: IrrigationDesign) -> None:
        services.new_design_version(ctx, design_id=obj.id)


class DesignChildMixin:
    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        parent = obj.design if isinstance(obj, BomLine) else obj.quote
        return platform_context(
            request, organization_id=parent.organization_id, farm_id=parent.farm_id
        )


@admin.register(BomLine)
class BomLineAdmin(DesignChildMixin, ServiceAdmin):
    """Manual lines are added to a draft; any line can be linked to a catalogue item."""

    scope = "design"
    add_fields = ["component_type", "description", "quantity", "unit", "rationale"]
    change_fields = ["catalog_item"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> BomLine:
        design = data.pop("design")
        return services.add_manual_bom_line(ctx, design_id=design.id, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.link_bom_line(
            ctx, design_id=obj.design_id, bom_line_id=obj.id, catalog_item=changes["catalog_item"]
        )


class QuoteLineInline(ReadOnlyTabularInline):
    model = QuoteLine


class DecisionForm(forms.Form):
    status = forms.ChoiceField(
        label="Décision",
        choices=[(Quote.Status.ACCEPTED, "Accepté"), (Quote.Status.REJECTED, "Refusé")],
    )


@admin.register(Quote)
class QuoteAdmin(ServiceAdmin):
    """Quote workflow: create from a design (prices copied) → adjust → issue → decision."""

    scope = "design"
    add_fields = ["price_list", "currency", "notes"]
    change_fields = ["discount_amount", "tax_rate", "notes"]
    inlines = [QuoteLineInline]
    actions = ["issue", "decide"]

    def can_change(self, obj: Any) -> bool:
        return obj.status == Quote.Status.DRAFT

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Quote:
        return services.create_quote(
            ctx,
            design_id=data["design"].id,
            price_list=data.get("price_list"),
            currency=data.get("currency") or None,
            notes=data.get("notes", ""),
        )

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_quote(
            ctx, quote_id=obj.id, expected_version=expected_version, data=changes
        )

    @service_action("Émettre les devis")
    def issue(self, ctx: TenantContext, obj: Quote) -> None:
        services.issue_quote(ctx, quote_id=obj.id, expected_version=obj.version)

    @service_action("Enregistrer la décision du client", form=DecisionForm)
    def decide(self, ctx: TenantContext, obj: Quote, status: str) -> None:
        services.decide_quote(ctx, quote_id=obj.id, expected_version=obj.version, status=status)


@admin.register(QuoteLine)
class QuoteLineAdmin(DesignChildMixin, ServiceAdmin):
    """Price of a line of a draft quote (copied prices can be adjusted before issuing)."""

    change_fields = ["unit_price", "notes"]

    def version_of(self, obj: Any) -> int | None:
        return obj.quote.version

    def can_change(self, obj: Any) -> bool:
        return obj.quote.status == Quote.Status.DRAFT

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        line = {"id": obj.id, "unit_price": obj.unit_price, "notes": obj.notes, **changes}
        services.update_quote(
            ctx, quote_id=obj.quote_id, expected_version=expected_version, data={"lines": [line]}
        )
        return QuoteLine.objects.get(pk=obj.pk)
