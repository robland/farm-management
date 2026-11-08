"""Parametric sizing for sprinkler / micro-sprinkler systems (AGRONOMY_ENGINE.md §5.4)."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from agronomy_engine.errors import present, require, require_positive
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import lph_to_m3h, q


@dataclass(frozen=True)
class SprinklerInput:
    sprinkler_count: int | None
    sprinkler_flow_lph: Decimal | None
    spacing_along_m: Decimal | None
    spacing_between_m: Decimal | None
    sector_count: int | None


def compute_sprinkler(data: SprinklerInput) -> CalculationResult:
    require(asdict(data), list(asdict(data)))
    count = present(data.sprinkler_count, "sprinkler_count")
    flow = present(data.sprinkler_flow_lph, "sprinkler_flow_lph")
    along = present(data.spacing_along_m, "spacing_along_m")
    between = present(data.spacing_between_m, "spacing_between_m")
    sectors = present(data.sector_count, "sector_count")
    for name, value in asdict(data).items():
        require_positive(name, value)
    total_lph = count * flow
    return CalculationResult(
        calc_type="irrigation.sprinkler",
        inputs={
            "sprinkler_count": Quantity(count, "asperseurs"),
            "sprinkler_flow_lph": Quantity(flow, "L/h"),
            "spacing_along_m": Quantity(along, "m"),
            "spacing_between_m": Quantity(between, "m"),
            "sector_count": Quantity(sectors, "secteurs"),
        },
        outputs={
            "total_flow_m3h": Quantity(q(lph_to_m3h(total_lph), 4), "m3/h"),
            "sector_flow_m3h": Quantity(q(lph_to_m3h(total_lph) / sectors, 4), "m3/h"),
            "application_rate_mm_per_h": Quantity(q(flow / (along * between), 3), "mm/h"),
        },
        formula="Qt = n × q ; Qs = Qt / secteurs ; I (mm/h) = q / (e1 × e2)",
        assumptions=["Calcul paramétrique simple : pas de calcul hydraulique automatique."],
    )
