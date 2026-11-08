"""Plans are designed online (OPEN_QUESTIONS Q7) but pulled for offline consultation (FR-110)."""

from apps.production_plans import services
from apps.production_plans.models import Campaign, CropCycle, PlanVersion, ProductionPlan
from apps.production_plans.serializers import (
    CampaignSerializer,
    CropCycleSerializer,
    PlanVersionSerializer,
    ProductionPlanSerializer,
)
from apps.synchronization.registry import EntityHandler, MergeStrategy, register

for entity_type, model, serializer in (
    (services.CAMPAIGN_ENTITY, Campaign, CampaignSerializer),
    (services.PLAN_ENTITY, ProductionPlan, ProductionPlanSerializer),
    (services.VERSION_ENTITY, PlanVersion, PlanVersionSerializer),
    (services.CYCLE_ENTITY, CropCycle, CropCycleSerializer),
):
    register(
        EntityHandler(
            entity_type=entity_type,
            model=model,
            serializer_class=serializer,
            read_permission=services.VIEW,
            write_permission=services.EDIT,
            strategy=MergeStrategy.STRICT,
        )
    )
