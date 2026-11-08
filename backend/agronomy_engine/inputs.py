"""Input quantities from doses and product composition (AGRONOMY_ENGINE.md §6, FR-050).

The engine never provides a dose: doses come from a validated document or a
user. It only converts a dose into product quantities using the declared
composition of the product.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from agronomy_engine.errors import InvalidInputError, MissingInputError, present, require_positive
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import G_PER_KG, M2_PER_HA, q

# Oxide <-> element mass ratios (molar masses): P = P2O5 × 0.4364 ; K = K2O × 0.8301.
ELEMENT_PER_OXIDE = {"P2O5": ("P", Decimal("0.4364")), "K2O": ("K", Decimal("0.8301"))}
OXIDE_OF_ELEMENT = {
    element: (oxide, ratio) for oxide, (element, ratio) in ELEMENT_PER_OXIDE.items()
}

PER_HA, PER_M2, PER_PLANT = "per_ha", "per_m2", "per_plant"
MASS_UNITS = {"kg": Decimal(1), "g": 1 / G_PER_KG}
VOLUME_UNITS = {"l": Decimal(1), "ml": Decimal("0.001")}


def nutrient_fraction(composition: dict[str, Decimal], nutrient: str) -> tuple[Decimal, str]:
    """Mass fraction (0..1) of `nutrient` in the product, converting oxide/element forms."""
    if nutrient in composition:
        return composition[nutrient] / 100, "déclarée"
    if nutrient in OXIDE_OF_ELEMENT:  # wanted P, composition in P2O5
        oxide, ratio = OXIDE_OF_ELEMENT[nutrient]
        if oxide in composition:
            return composition[oxide] / 100 * ratio, f"convertie depuis {oxide} (× {ratio})"
    if nutrient in ELEMENT_PER_OXIDE:  # wanted P2O5, composition in P
        element, ratio = ELEMENT_PER_OXIDE[nutrient]
        if element in composition:
            return composition[element] / 100 / ratio, f"convertie depuis {element} (÷ {ratio})"
    raise InvalidInputError("composition", f"le produit ne contient pas {nutrient}")


@dataclass(frozen=True)
class NutrientDoseInput:
    """Product quantity needed to supply a nutrient dose (kg of nutrient per ha)."""

    target_nutrient: str | None
    nutrient_dose_kg_per_ha: Decimal | None
    area_m2: Decimal | None
    composition_pct: dict[str, Decimal] = field(default_factory=dict)
    density_kg_per_l: Decimal | None = None


def compute_nutrient_dose(data: NutrientDoseInput) -> CalculationResult:
    missing = [
        n
        for n in ("target_nutrient", "nutrient_dose_kg_per_ha", "area_m2")
        if getattr(data, n) is None
    ]
    if not data.composition_pct:
        missing.append("composition_pct")
    if missing:
        raise MissingInputError(missing)
    nutrient_code = present(data.target_nutrient, "target_nutrient")
    dose = present(data.nutrient_dose_kg_per_ha, "nutrient_dose_kg_per_ha")
    area = present(data.area_m2, "area_m2")
    require_positive("nutrient_dose_kg_per_ha", dose)
    require_positive("area_m2", area)
    for nutrient, pct in data.composition_pct.items():
        if not 0 <= pct <= 100:
            raise InvalidInputError(f"composition_pct.{nutrient}", "doit être entre 0 et 100")
    fraction, how = nutrient_fraction(data.composition_pct, nutrient_code)
    if fraction <= 0:
        raise InvalidInputError("composition", f"teneur nulle en {nutrient_code}")
    # Divide last to keep exact results where possible.
    product_kg = dose * area / (M2_PER_HA * fraction)
    product_kg_per_ha = dose / fraction
    co_applied = {
        nutrient: Quantity(q(product_kg_per_ha * pct / 100, 3), "kg/ha")
        for nutrient, pct in data.composition_pct.items()
        if nutrient != nutrient_code
    }
    outputs = {
        "product_kg": Quantity(q(product_kg, 3), "kg"),
        "product_kg_per_ha": Quantity(q(product_kg_per_ha, 3), "kg/ha"),
        "nutrient_fraction": Quantity(q(fraction, 6), "ratio"),
    }
    formula = "produit (kg) = dose nutriment (kg/ha) × surface (ha) / teneur"
    if data.density_kg_per_l is not None:
        require_positive("density_kg_per_l", data.density_kg_per_l)
        outputs["product_l"] = Quantity(q(product_kg / data.density_kg_per_l, 3), "L")
        formula += " ; volume (L) = masse / densité"
    return CalculationResult(
        calc_type="inputs.nutrient_dose",
        inputs={
            "target_nutrient": Quantity(nutrient_code),
            "nutrient_dose_kg_per_ha": Quantity(dose, "kg/ha"),
            "area_m2": Quantity(area, "m2"),
            **{f"composition.{k}": Quantity(v, "%") for k, v in data.composition_pct.items()},
        },
        outputs=outputs,
        formula=formula,
        assumptions=[f"Teneur en {nutrient_code} {how} ; composition déclarée du produit."],
        details={"co_applied_kg_per_ha": {k: v.to_dict() for k, v in co_applied.items()}},
    )


@dataclass(frozen=True)
class ProductDoseInput:
    """Total product quantity from a product dose expressed per ha, per m² or per plant."""

    dose_value: Decimal | None
    dose_unit: str | None  # kg | g | l | ml
    basis: str | None  # per_ha | per_m2 | per_plant
    area_m2: Decimal | None = None
    plant_count: int | None = None
    density_kg_per_l: Decimal | None = None


def compute_product_dose(data: ProductDoseInput) -> CalculationResult:
    missing = [n for n in ("dose_value", "dose_unit", "basis") if getattr(data, n) is None]
    if data.basis in {PER_HA, PER_M2} and data.area_m2 is None:
        missing.append("area_m2")
    if data.basis == PER_PLANT and data.plant_count is None:
        missing.append("plant_count")
    if missing:
        raise MissingInputError(missing)
    dose = present(data.dose_value, "dose_value")
    dose_unit = present(data.dose_unit, "dose_unit")
    require_positive("dose_value", dose)
    if dose_unit in MASS_UNITS:
        base_unit, factor = "kg", MASS_UNITS[dose_unit]
    elif dose_unit in VOLUME_UNITS:
        base_unit, factor = "L", VOLUME_UNITS[dose_unit]
    else:
        raise InvalidInputError("dose_unit", "unité inconnue (kg, g, l, ml)")
    if data.basis == PER_HA:
        area = present(data.area_m2, "area_m2")
        multiplier, label = area / M2_PER_HA, f"{area} m² / 10 000"
    elif data.basis == PER_M2:
        area = present(data.area_m2, "area_m2")
        multiplier, label = area, f"{area} m²"
    elif data.basis == PER_PLANT:
        plants = present(data.plant_count, "plant_count")
        multiplier, label = Decimal(plants), f"{plants} plants"
    else:
        raise InvalidInputError("basis", "base inconnue (per_ha, per_m2, per_plant)")
    require_positive("multiplier", multiplier)
    total = dose * factor * multiplier
    outputs = {"total_quantity": Quantity(q(total, 4), base_unit)}
    if base_unit == "L" and data.density_kg_per_l is not None:
        outputs["total_mass_kg"] = Quantity(q(total * data.density_kg_per_l, 4), "kg")
    return CalculationResult(
        calc_type="inputs.product_dose",
        inputs={"dose_value": Quantity(dose, dose_unit), "basis": Quantity(data.basis)},
        outputs=outputs,
        formula=f"quantité = dose × facteur d'unité × ({label})",
        assumptions=[
            "Dose fournie par l'utilisateur ou un document validé (jamais par le système)."
        ],
    )


@dataclass(frozen=True)
class WaterNeedInput:
    et0_mm_per_day: Decimal | None
    kc: Decimal | None
    application_efficiency_rate: Decimal | None
    area_m2: Decimal | None


def compute_water_need(data: WaterNeedInput) -> CalculationResult:
    missing = [
        n
        for n in ("et0_mm_per_day", "kc", "application_efficiency_rate", "area_m2")
        if getattr(data, n) is None
    ]
    if missing:
        raise MissingInputError(missing)
    et0 = present(data.et0_mm_per_day, "et0_mm_per_day")
    kc = present(data.kc, "kc")
    efficiency = present(data.application_efficiency_rate, "application_efficiency_rate")
    area = present(data.area_m2, "area_m2")
    for name, value in (("et0_mm_per_day", et0), ("kc", kc), ("area_m2", area)):
        require_positive(name, value)
    if not 0 < efficiency <= 1:
        raise InvalidInputError("application_efficiency_rate", "doit être entre 0 et 1")
    etc = kc * et0
    net = etc * area
    gross = net / efficiency
    return CalculationResult(
        calc_type="irrigation.water_need",
        inputs={
            "et0_mm_per_day": Quantity(et0, "mm/j"),
            "kc": Quantity(kc, "ratio"),
            "application_efficiency_rate": Quantity(efficiency, "ratio"),
            "area_m2": Quantity(area, "m2"),
        },
        outputs={
            "etc_mm_per_day": Quantity(q(etc, 3), "mm/j"),
            "net_volume_l_per_day": Quantity(q(net, 1), "L/j"),
            "gross_volume_l_per_day": Quantity(q(gross, 1), "L/j"),
        },
        formula="ETc = Kc × ET0 ; Vnet = ETc × S ; Vbrut = Vnet / Ea",
        assumptions=["1 mm sur 1 m² = 1 L ; volume journalier (et non débit instantané)."],
    )
