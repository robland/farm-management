"""Input quantity reference cases. Doses are arbitrary arithmetic examples, not advice."""

from decimal import Decimal as D

import pytest

from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.inputs import (
    NutrientDoseInput,
    ProductDoseInput,
    WaterNeedInput,
    compute_nutrient_dose,
    compute_product_dose,
    compute_water_need,
    nutrient_fraction,
)


def test_nutrient_dose_with_declared_content():
    result = compute_nutrient_dose(NutrientDoseInput("N", D(100), D(5000), {"N": D(46)}))
    # 100 kg N/ha × 0.5 ha / 0.46 = 108.696 kg
    assert result.output("product_kg") == D("108.696")
    assert result.output("product_kg_per_ha") == D("217.391")


def test_oxide_to_element_conversion_is_explicit():
    fraction, how = nutrient_fraction({"P2O5": D(15)}, "P")
    assert fraction == D("0.15") * D("0.4364") and "P2O5" in how
    result = compute_nutrient_dose(NutrientDoseInput("P", D(20), D(10000), {"P2O5": D(15)}))
    assert result.output("product_kg") == D("305.530")
    back, _ = nutrient_fraction({"K": D(10)}, "K2O")
    assert back == D("0.1") / D("0.8301")


def test_co_applied_nutrients_are_reported():
    result = compute_nutrient_dose(
        NutrientDoseInput(
            "N", D(30), D(10000), {"N": D(15), "P2O5": D(15), "K2O": D(15)}, density_kg_per_l=None
        )
    )
    assert result.output("product_kg") == D("200.000")
    assert result.details["co_applied_kg_per_ha"]["P2O5"]["value"] == "30.000"


def test_liquid_fertilizer_volume():
    result = compute_nutrient_dose(
        NutrientDoseInput("N", D(10), D(10000), {"N": D(20)}, density_kg_per_l=D("1.25"))
    )
    assert result.output("product_l") == D("40.000")  # 50 kg / 1.25


def test_nutrient_dose_errors():
    with pytest.raises(MissingInputError) as exc:
        compute_nutrient_dose(NutrientDoseInput("N", None, D(1), {}))
    assert set(exc.value.fields) == {"nutrient_dose_kg_per_ha", "composition_pct"}
    with pytest.raises(InvalidInputError):
        compute_nutrient_dose(NutrientDoseInput("N", D(10), D(1), {"K2O": D(50)}))
    with pytest.raises(InvalidInputError):
        compute_nutrient_dose(NutrientDoseInput("N", D(10), D(1), {"N": D(150)}))


def test_product_dose_bases():
    per_plant = compute_product_dose(ProductDoseInput(D(10), "g", "per_plant", plant_count=1414))
    assert per_plant.output("total_quantity") == D("14.1400")
    per_ha = compute_product_dose(
        ProductDoseInput(D(2), "l", "per_ha", area_m2=D(5000), density_kg_per_l=D("1.2"))
    )
    assert per_ha.output("total_quantity") == D("1.0000")
    assert per_ha.outputs["total_quantity"].unit == "L"
    assert per_ha.output("total_mass_kg") == D("1.2000")
    per_m2 = compute_product_dose(ProductDoseInput(D(50), "ml", "per_m2", area_m2=D(100)))
    assert per_m2.output("total_quantity") == D("5.0000")


def test_product_dose_errors():
    with pytest.raises(MissingInputError):
        compute_product_dose(ProductDoseInput(D(1), "kg", "per_plant"))
    with pytest.raises(InvalidInputError):
        compute_product_dose(ProductDoseInput(D(1), "bucket", "per_ha", area_m2=D(1)))
    with pytest.raises(InvalidInputError):
        compute_product_dose(ProductDoseInput(D(1), "kg", "per_tree", area_m2=D(1)))


def test_water_need():
    result = compute_water_need(WaterNeedInput(D(5), D("0.8"), D("0.9"), D(1000)))
    assert result.output("etc_mm_per_day") == D("4.000")
    assert result.output("net_volume_l_per_day") == D("4000.0")
    assert result.output("gross_volume_l_per_day") == D("4444.4")
    with pytest.raises(MissingInputError):
        compute_water_need(WaterNeedInput(None, D(1), D(1), D(1)))
