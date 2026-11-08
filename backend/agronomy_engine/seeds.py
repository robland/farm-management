"""Seed requirement (AGRONOMY_ENGINE.md §4, FR-032)."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from agronomy_engine.errors import (
    InvalidInputError,
    MissingInputError,
    present,
    require,
    require_non_negative,
    require_positive,
    require_rate,
)
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import G_PER_KG, ceil_int, q

DIRECT_SEEDING = "direct_seeding"
TRANSPLANTING = "transplanting"


@dataclass(frozen=True)
class SeedInput:
    plant_count: int | None
    plants_per_hole: int | None
    seeds_per_hole: int | None
    germination_rate: Decimal | None
    safety_margin_rate: Decimal | None
    planting_method: str = DIRECT_SEEDING
    nursery_success_rate: Decimal | None = None
    seeds_per_gram: Decimal | None = None
    thousand_seed_weight_g: Decimal | None = None
    seed_package_size_g: Decimal | None = None


def compute_seeds(data: SeedInput) -> CalculationResult:
    values = asdict(data)
    required = [
        "plant_count",
        "plants_per_hole",
        "seeds_per_hole",
        "germination_rate",
        "safety_margin_rate",
    ]
    if data.planting_method == TRANSPLANTING:
        required.append("nursery_success_rate")
    elif data.planting_method != DIRECT_SEEDING:
        raise InvalidInputError("planting_method", "méthode inconnue")
    missing = [n for n in required if values[n] is None]
    if data.seeds_per_gram is None and data.thousand_seed_weight_g is None:
        missing.append("seeds_per_gram|thousand_seed_weight_g")
    if missing:
        raise MissingInputError(missing)
    require(values, required)

    plants = present(data.plant_count, "plant_count")
    k = present(data.plants_per_hole, "plants_per_hole")
    s = present(data.seeds_per_hole, "seeds_per_hole")
    g = present(data.germination_rate, "germination_rate")
    m = present(data.safety_margin_rate, "safety_margin_rate")
    require_positive("plant_count", plants)
    require_positive("plants_per_hole", k)
    require_positive("seeds_per_hole", s)
    require_rate("germination_rate", g)
    require_non_negative("safety_margin_rate", m)

    assumptions = [
        "Le taux de germination corrige le nombre de graines semées par poquet ou alvéole.",
        "La marge de sécurité s'applique au nombre de graines avant correction de germination.",
    ]
    inputs = {
        "plant_count": Quantity(plants, "plants"),
        "plants_per_hole": Quantity(k, "plants/poquet"),
        "seeds_per_hole": Quantity(s, "graines/poquet"),
        "germination_rate": Quantity(g, "ratio"),
        "safety_margin_rate": Quantity(m, "ratio"),
        "planting_method": Quantity(data.planting_method),
    }
    if data.planting_method == TRANSPLANTING:
        r = present(data.nursery_success_rate, "nursery_success_rate")
        require_rate("nursery_success_rate", r)
        inputs["nursery_success_rate"] = Quantity(r, "ratio")
        # One seedling per transplanted plant: k plants per hole are k seedlings.
        sowing_points = plants
        formula = "points = N plants ; graines = ceil(points × s × (1 + m) / (g × r))"
        assumptions.append("Repiquage : un plant repiqué par plant prévu, semé en alvéole.")
    else:
        r = Decimal(1)
        sowing_points = ceil_int(Decimal(plants) / Decimal(k))
        formula = "poquets = ceil(N / k) ; graines = ceil(poquets × s × (1 + m) / g)"

    seeds = ceil_int(Decimal(sowing_points) * s * (1 + m) / (g * r))
    if data.seeds_per_gram is not None:
        require_positive("seeds_per_gram", data.seeds_per_gram)
        mass_g = Decimal(seeds) / data.seeds_per_gram
        inputs["seeds_per_gram"] = Quantity(data.seeds_per_gram, "graines/g")
        formula += " ; masse (g) = graines / graines_par_g"
    else:
        tsw = present(data.thousand_seed_weight_g, "thousand_seed_weight_g")
        require_positive("thousand_seed_weight_g", tsw)
        mass_g = Decimal(seeds) * tsw / Decimal(1000)
        inputs["thousand_seed_weight_g"] = Quantity(tsw, "g/1000 graines")
        formula += " ; masse (g) = graines × PMG / 1000"

    outputs = {
        "sowing_points": Quantity(sowing_points, "poquets ou alvéoles"),
        "seed_count": Quantity(seeds, "graines"),
        "seed_mass_g": Quantity(q(mass_g, 2), "g"),
        "seed_mass_kg": Quantity(q(mass_g / G_PER_KG, 4), "kg"),
    }
    if data.seed_package_size_g is not None:
        require_positive("seed_package_size_g", data.seed_package_size_g)
        inputs["seed_package_size_g"] = Quantity(data.seed_package_size_g, "g")
        outputs["packages"] = Quantity(ceil_int(mass_g / data.seed_package_size_g), "sachets")
        formula += " ; sachets = ceil(masse / conditionnement)"
    return CalculationResult(
        calc_type="planting.seeds",
        inputs=inputs,
        outputs=outputs,
        formula=formula,
        assumptions=assumptions,
    )
