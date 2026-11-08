from decimal import Decimal as D

import pytest

from agronomy_engine.errors import MissingInputError
from agronomy_engine.yield_ import HarvestLine, YieldInput, compute_yield, to_kg


def test_unit_conversion_requires_measured_factor():
    assert to_kg(D(2), "t", None) == (D(2000), D(1000))
    assert to_kg(D(10), "crate", D("12.5")) == (D("125.0"), D("12.5"))
    with pytest.raises(MissingInputError):
        to_kg(D(10), "crate", None)


def test_yield_reference():
    result = compute_yield(
        YieldInput(
            harvested_area_m2=D(1000),
            harvests=[HarvestLine(D(1200), D(50)), HarvestLine(D(300), D(0), marketable=False)],
            target_yield_kg_per_ha=D(15000),
            total_cost=D(450000),
            cost_currency="XAF",
        )
    )
    assert result.output("gross_harvest_kg") == D("1500.000")
    assert result.output("marketable_harvest_kg") == D("1200.000")
    assert result.output("gross_yield_kg_per_ha") == D("15000.00")
    assert result.output("marketable_yield_kg_per_ha") == D("12000.00")
    assert result.output("loss_rate") == D("0.0323")  # 50 / 1550
    assert result.output("gap_to_target_pct") == D("-20.00")
    assert result.output("cost_per_kg") == D("375.0000")


def test_yield_without_harvest():
    result = compute_yield(YieldInput(harvested_area_m2=D(500)))
    assert result.output("gross_yield_kg_per_ha") == D("0.00")
    assert result.warnings
    with pytest.raises(MissingInputError):
        compute_yield(YieldInput(harvested_area_m2=None))
