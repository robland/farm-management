"""Catalogue of technical data keys with their canonical unit (NFR-007).

This catalogue defines *which* information can be recorded and in *which
unit*. It contains no agronomic value: values come from validated documents
or user input only (CLAUDE.md §9, §16).
"""

import re
from dataclasses import dataclass
from decimal import Decimal

# Crop phases of FR-033. Plans may use other codes matching PHASE_CODE_PATTERN.
PHASE_CODES = [
    "soil_preparation",
    "sowing",
    "nursery",
    "transplanting",
    "vegetative",
    "flowering",
    "fruiting",
    "maturation",
    "harvest",
]
PHASE_CODE_PATTERN = re.compile(r"^[a-z][a-z_]{1,39}$")


@dataclass(frozen=True)
class KeySpec:
    label: str
    unit: str
    kind: str = "decimal"  # "decimal" | "text"
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    min_exclusive: bool = False


def _positive(label: str, unit: str) -> KeySpec:
    return KeySpec(label, unit, min_value=Decimal(0), min_exclusive=True)


def _rate(label: str) -> KeySpec:
    return KeySpec(label, "ratio", min_value=Decimal(0), max_value=Decimal(1), min_exclusive=True)


def _text(label: str) -> KeySpec:
    return KeySpec(label, "", kind="text")


TECHNICAL_KEYS: dict[str, KeySpec] = {
    "row_spacing": _positive("Écartement entre lignes", "m"),
    "plant_spacing": _positive("Écartement entre plants", "m"),
    "plants_per_hole": _positive("Plants par poquet", "count"),
    "seeds_per_hole": _positive("Graines par poquet", "count"),
    "germination_rate": _rate("Taux de germination"),
    "seeds_per_gram": _positive("Graines par gramme", "count/g"),
    "thousand_seed_weight": _positive("Poids de mille graines", "g"),
    "nursery_duration": _positive("Durée en pépinière", "days"),
    "cycle_duration": _positive("Durée du cycle", "days"),
    "days_to_first_harvest": _positive("Jours jusqu'à la première récolte", "days"),
    "harvest_duration": _positive("Durée de récolte", "days"),
    "yield_potential": _positive("Rendement potentiel", "kg/ha"),
    "average_fruit_weight": _positive("Poids moyen d'un fruit", "kg"),
    "temperature_min": KeySpec("Température minimale", "degC"),
    "temperature_max": KeySpec("Température maximale", "degC"),
    "soil_ph_min": KeySpec("pH minimal", "pH", min_value=Decimal(0), max_value=Decimal(14)),
    "soil_ph_max": KeySpec("pH maximal", "pH", min_value=Decimal(0), max_value=Decimal(14)),
    "resistances": _text("Résistances et tolérances"),
    "recommendations": _text("Recommandations du semencier"),
}

_PHASE_DURATION = re.compile(r"^phase\.(?P<code>[a-z][a-z_]{1,39})\.duration_days$")
_KC = re.compile(r"^kc\.(?P<code>[a-z][a-z_]{1,39})$")


def get_key_spec(key: str) -> KeySpec | None:
    if key in TECHNICAL_KEYS:
        return TECHNICAL_KEYS[key]
    match = _PHASE_DURATION.match(key)
    if match:
        return _positive(f"Durée de la phase {match['code']}", "days")
    match = _KC.match(key)
    if match:
        # Crop coefficient Kc (FAO-56 convention): dimensionless and positive.
        return KeySpec(
            f"Coefficient cultural Kc ({match['code']})",
            "ratio",
            min_value=Decimal(0),
            max_value=Decimal(3),
            min_exclusive=True,
        )
    return None


def phase_durations(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Extract `{phase_code: duration_days}` from a key/value mapping."""
    result = {}
    for key, value in values.items():
        match = _PHASE_DURATION.match(key)
        if match:
            result[match["code"]] = value
    return result
