from apps.agronomy.models import (
    InputProduct,
    Observation,
    PlannedFertilization,
    PlannedIrrigation,
    PlannedPhytoIntervention,
)
from apps.core.admin import register_read_only

# Doses and products are never edited outside the validated plan flow (CLAUDE.md §9).
register_read_only(
    InputProduct,
    PlannedFertilization,
    PlannedPhytoIntervention,
    PlannedIrrigation,
    Observation,
)
