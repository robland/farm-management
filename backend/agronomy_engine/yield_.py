"""Yields from measured harvests (AGRONOMY_ENGINE.md §9, FR-091, FR-092).

Only measured quantities are used: a non-mass unit must have a measured
conversion factor (kg per unit); the engine never assumes an average weight.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from agronomy_engine.errors import InvalidInputError, MissingInputError, require_positive
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import M2_PER_HA, q

MASS_UNITS = {"kg": Decimal(1), "g": Decimal("0.001"), "t": Decimal(1000)}


def to_kg(quantity: Decimal, unit: str, kg_per_unit: Decimal | None) -> tuple[Decimal, Decimal]:
    """Return (kg, factor used)."""
    if unit in MASS_UNITS:
        return quantity * MASS_UNITS[unit], MASS_UNITS[unit]
    if kg_per_unit is None:
        raise MissingInputError(
            [f"conversion.{unit}"],
            "facteur kg/unité mesuré obligatoire pour une unité non massique",
        )
    require_positive("kg_per_unit", kg_per_unit)
    return quantity * kg_per_unit, kg_per_unit


@dataclass(frozen=True)
class HarvestLine:
    quantity_kg: Decimal
    loss_kg: Decimal = Decimal(0)
    marketable: bool = True


@dataclass(frozen=True)
class YieldInput:
    harvested_area_m2: Decimal | None
    harvests: list[HarvestLine] = field(default_factory=list)
    target_yield_kg_per_ha: Decimal | None = None
    total_cost: Decimal | None = None
    cost_currency: str = ""


def compute_yield(data: YieldInput) -> CalculationResult:
    if data.harvested_area_m2 is None:
        raise MissingInputError(["harvested_area_m2"])
    require_positive("harvested_area_m2", data.harvested_area_m2)
    for index, line in enumerate(data.harvests):
        if line.quantity_kg < 0 or line.loss_kg < 0:
            raise InvalidInputError(f"harvests.{index}", "quantités négatives")
    gross = sum((line.quantity_kg for line in data.harvests), Decimal(0))
    marketable = sum((line.quantity_kg for line in data.harvests if line.marketable), Decimal(0))
    losses = sum((line.loss_kg for line in data.harvests), Decimal(0))
    area = data.harvested_area_m2
    outputs = {
        "gross_harvest_kg": Quantity(q(gross, 3), "kg"),
        "marketable_harvest_kg": Quantity(q(marketable, 3), "kg"),
        "losses_kg": Quantity(q(losses, 3), "kg"),
        # Divide last: kg × 10 000 / m².
        "gross_yield_kg_per_ha": Quantity(q(gross * M2_PER_HA / area, 2), "kg/ha"),
        "marketable_yield_kg_per_ha": Quantity(q(marketable * M2_PER_HA / area, 2), "kg/ha"),
        "harvest_count": Quantity(len(data.harvests), "récoltes"),
    }
    formula = "rendement (kg/ha) = quantité récoltée (kg) × 10 000 / surface récoltée (m²)"
    if gross + losses > 0:
        outputs["loss_rate"] = Quantity(q(losses / (gross + losses), 4), "ratio")
        formula += " ; taux de pertes = pertes / (récolte + pertes)"
    warnings = []
    if not data.harvests:
        warnings.append("Aucune récolte enregistrée.")
    if data.target_yield_kg_per_ha:
        achieved = marketable * M2_PER_HA / area
        gap = (achieved - data.target_yield_kg_per_ha) / data.target_yield_kg_per_ha * 100
        outputs["gap_to_target_pct"] = Quantity(q(gap, 2), "%")
        formula += " ; écart = (réel − objectif) / objectif"
    if data.total_cost is not None:
        outputs["total_cost"] = Quantity(data.total_cost, data.cost_currency)
        if marketable > 0:
            outputs["cost_per_kg"] = Quantity(
                q(data.total_cost / marketable, 4), f"{data.cost_currency}/kg"
            )
            formula += " ; coût/kg = coûts / quantité commercialisable"
        else:
            warnings.append("Coût par kg non calculable : aucune quantité commercialisable.")
    return CalculationResult(
        calc_type="harvest.yield",
        inputs={
            "harvested_area_m2": Quantity(area, "m2"),
            "target_yield_kg_per_ha": Quantity(data.target_yield_kg_per_ha, "kg/ha"),
        },
        outputs=outputs,
        formula=formula,
        assumptions=[
            "Quantités mesurées uniquement ; les lots de qualité « rejeté » ne sont pas "
            "commercialisables."
        ],
        warnings=warnings,
    )
