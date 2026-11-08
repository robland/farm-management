"""Builders for validated technical data and plans. Values are fictitious test inputs."""

from decimal import Decimal as D

from django.utils import timezone

from apps.organizations.models import Organization
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet, TechnicalDocument, Variety
from tests.factories_catalog import make_sheet, make_variety

TEST_TECHNICAL_VALUES = {
    "row_spacing": D("1.5"),
    "plant_spacing": D("0.5"),
    "plants_per_hole": D(1),
    "seeds_per_hole": D(2),
    "germination_rate": D("0.8"),
    "seeds_per_gram": D(25),
    "phase.soil_preparation.duration_days": D(7),
    "phase.sowing.duration_days": D(1),
    "phase.vegetative.duration_days": D(30),
    "phase.harvest.duration_days": D(20),
}


def make_validated_plan(ctx, variety: Variety, parcel, *, area=D(1000), start=None, program=None):
    """Create, complete and validate a plan through the services. Returns the version.

    `program(ctx, version)` may add programme items to the draft before validation.
    """
    import datetime

    from apps.production_plans import services as plans

    campaign = plans.create_campaign(
        ctx,
        data={
            "name": "Campagne test",
            "start_date": datetime.date(2026, 1, 1),
            "end_date": datetime.date(2026, 12, 31),
        },
    )
    plan = plans.create_plan(ctx, campaign_id=campaign.id, variety_id=variety.id, name="Plan")
    version = plan.versions.get()
    plans.prefill_from_technical_data(ctx, version_id=version.id, expected_version=None)
    version.refresh_from_db()
    plans.set_allocations(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        allocations=[{"parcel": parcel, "allocated_area_m2": area, "non_plantable_area_m2": D(0)}],
    )
    version.refresh_from_db()
    plans.update_planting_spec(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        changes={"planting_method": "direct_seeding", "safety_margin_rate": D("0.1")},
    )
    version.refresh_from_db()
    plans.update_header(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        changes={"planned_start_date": start or datetime.date(2026, 1, 1)},
    )
    version.refresh_from_db()
    plans.compute_version(ctx, version_id=version.id)
    version.refresh_from_db()
    if program is not None:
        program(ctx, version)
        version.refresh_from_db()
    plans.validate_version(ctx, version_id=version.id, expected_version=version.version)
    version.refresh_from_db()
    return version


def make_validated_variety(org: Organization, admin) -> Variety:
    variety = make_variety(org)
    document = TechnicalDocument.objects.create(
        organization=org, variety=variety, file=make_sheet(org, admin)
    )
    data_set = TechnicalDataSet.objects.create(
        organization=org,
        variety=variety,
        version_number=1,
        source_document=document,
        status=TechnicalDataSet.Status.VALIDATED,
        validated_by=admin,
        validated_at=timezone.now(),
    )
    for key, value in TEST_TECHNICAL_VALUES.items():
        TechnicalDataItem.objects.create(
            data_set=data_set,
            key=key,
            value_numeric=value,
            unit="days" if key.startswith("phase.") else "",
            provenance=(
                TechnicalDataItem.Provenance.DOCUMENT
                if key == "row_spacing"
                else TechnicalDataItem.Provenance.USER_INPUT
            ),
            source_page=1 if key == "row_spacing" else None,
            source_quote="extrait" if key == "row_spacing" else "",
            validated=True,
            validated_by=admin,
        )
    return variety
