"""Hydraulic and quotation reference cases (arithmetic checks, not design recommendations)."""

from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.irrigation.bom import BomInput, compute_bom
from agronomy_engine.irrigation.drip import (
    LATERAL,
    MAIN,
    SUBMAIN,
    DripInput,
    PipeSegment,
    christiansen_factor,
    compute_drip,
    hazen_williams_loss_m,
)
from agronomy_engine.irrigation.sprinkler import SprinklerInput, compute_sprinkler
from agronomy_engine.quotation import QuoteInput, QuoteLineInput, compute_quote


def drip(**overrides):
    base = dict(
        lateral_count=14,
        lateral_length_m=D(50),
        lateral_spacing_m=D("1.5"),
        emitter_spacing_m=D("0.3"),
        emitter_flow_lph=D(2),
        operating_pressure_bar=D(1),
        source_max_flow_m3h=D("2.5"),
    )
    return DripInput(**{**base, **overrides})


def test_drip_flows_and_sectors():
    result = compute_drip(drip())
    # ne = floor(50 / 0.3) = 166 ; NE = 166 × 14 = 2324 ; Qt = 4648 L/h = 4.648 m3/h
    assert result.output("emitters_per_lateral") == 166
    assert result.output("emitter_count") == 2324
    assert result.output("total_flow_lph") == D("4648.00")
    assert result.output("total_flow_m3h") == D("4.6480")
    assert result.output("application_rate_mm_per_h") == D("4.444")
    # sectors = ceil(4.648 / 2.5) = 2 ; Qs = 2.324 m3/h
    assert result.output("sector_count") == 2
    assert result.output("sector_flow_m3h") == D("2.3240")


def test_daily_volume_is_distinct_from_instant_flow():
    result = compute_drip(
        drip(
            irrigated_area_m2=D(1000),
            et0_mm_per_day=D(5),
            kc=D(1),
            application_efficiency_rate=D("0.9"),
        )
    )
    assert result.output("etc_mm_per_day") == D("5.000")
    assert result.output("net_daily_volume_l") == D("5000.0")
    assert result.output("gross_daily_volume_m3") == D("5.556")  # volume per day
    assert result.outputs["gross_daily_volume_m3"].unit == "m3/j"
    assert result.outputs["sector_flow_m3h"].unit == "m3/h"  # instantaneous flow
    # t = (5555.6 / 2) / 2324 = 1.195 h per sector
    assert result.output("irrigation_hours_per_sector") == D("1.20")
    assert result.output("total_irrigation_hours_per_day") == D("2.39")


def test_water_need_is_all_or_nothing():
    with pytest.raises(MissingInputError) as exc:
        compute_drip(drip(et0_mm_per_day=D(5)))
    assert set(exc.value.fields) == {"irrigated_area_m2", "kc", "application_efficiency_rate"}
    result = compute_drip(drip())
    assert any("Besoin en eau" in item for item in result.details["not_considered"])


def test_head_and_power_with_provided_components():
    result = compute_drip(
        drip(
            static_lift_m=D(5),
            elevation_difference_m=D(2),
            filter_head_loss_m=D(3),
            pump_efficiency_rate=D("0.5"),
        )
    )
    # HMT = 5 + 2 + 3 + 1 bar (10.197 m) = 20.197 m
    assert result.output("total_dynamic_head_m") == D("20.197")
    # Ph = 1000 × 9.80665 × (2.324 / 3600) × 20.197 ≈ 127.9 W ; Pa = Ph / 0.5
    assert result.output("hydraulic_power_w") == D("127.9")
    assert result.output("absorbed_power_w") == D("255.7")


def test_unprovided_head_components_are_listed():
    not_considered = compute_drip(drip()).details["not_considered"]
    assert {"Dénivelé", "Perte de charge de filtration"} <= set(not_considered)
    assert any("Pertes de charge linéaires" in item for item in not_considered)
    assert any("Rendement de la pompe" in item for item in not_considered)


def test_hazen_williams_reference_value():
    # Q = 1 L/s, L = 100 m, D = 50 mm, C = 140 -> about 0.68 m
    loss = hazen_williams_loss_m(D("0.001"), D(100), D("0.05"), D(140))
    assert D("0.67") < loss < D("0.69")


def test_christiansen_factor():
    assert christiansen_factor(1) == 1
    assert round(christiansen_factor(10), 4) == D("0.4022")
    assert christiansen_factor(1000) < christiansen_factor(10)


def test_segments_increase_head():
    segments = [
        PipeSegment(MAIN, D(80), D(50), D(140)),
        PipeSegment(SUBMAIN, D(20), D(40), D(140), outlets=7),
        PipeSegment(LATERAL, D(50), D("13.6"), D(140)),
    ]
    with_pipes = compute_drip(drip(segments=segments, fittings_loss_rate=D("0.1")))
    without = compute_drip(drip())
    assert with_pipes.output("friction_loss_m") > 0
    assert with_pipes.output("total_dynamic_head_m") > without.output("total_dynamic_head_m")
    assert len(with_pipes.details["segments"]) == 3


def test_submain_requires_outlets():
    with pytest.raises(MissingInputError):
        compute_drip(drip(segments=[PipeSegment(SUBMAIN, D(20), D(40), D(140))]))


def test_drip_missing_and_invalid():
    with pytest.raises(MissingInputError) as exc:
        compute_drip(drip(emitter_flow_lph=None, source_max_flow_m3h=None))
    assert set(exc.value.fields) == {"emitter_flow_lph", "source_max_flow_m3h|sector_count"}
    with pytest.raises(InvalidInputError):
        compute_drip(drip(lateral_length_m=D("0.1")))
    with pytest.raises(InvalidInputError):
        compute_drip(drip(sector_count=1))  # source cannot feed all laterals at once
    with pytest.raises(InvalidInputError):
        compute_drip(drip(source_max_flow_m3h=None, sector_count=20))  # > laterals


def test_explicit_sector_count_without_source():
    result = compute_drip(drip(source_max_flow_m3h=None, sector_count=7))
    assert result.output("sector_flow_m3h") == D("0.6640")


@given(flow=st.decimals(min_value=D("0.5"), max_value=D(8), places=1))
def test_total_flow_is_proportional_to_emitter_flow(flow):
    result = compute_drip(drip(emitter_flow_lph=flow, source_max_flow_m3h=None, sector_count=1))
    assert result.output("total_flow_lph") == D(2324) * flow


# --- BOM ----------------------------------------------------------------------------


def bom(**overrides):
    base = dict(
        lateral_count=14,
        lateral_length_m=D(50),
        emitter_count=2324,
        sector_count=2,
        installation_waste_rate=D("0.05"),
        dripline_roll_length_m=D(400),
        filter_count=1,
        include_pump=True,
        segments=[
            PipeSegment(MAIN, D(80), D(50), D(140)),
            PipeSegment(SUBMAIN, D(20), D(40), D(140), outlets=7),
        ],
    )
    return BomInput(**{**base, **overrides})


def test_bom_quantities_and_rationale():
    result, lines = compute_bom(bom())
    by_type = {}
    for line in lines:
        by_type.setdefault(line.component_type, []).append(line)
    dripline = by_type["dripline"][0]
    # 14 × 50 × 1.05 = 735 m -> ceil(735 / 400) = 2 rolls
    assert (dripline.quantity, dripline.unit) == (D(2), "roll")
    assert "400" in dripline.rationale
    assert result.output("dripline_length_m") == D("735.00")
    pipes = {line.description: line.quantity for line in by_type["pipe"]}
    assert pipes == {"Conduite principale Ø50 mm": D("84.00"), "Porte-rampe Ø40 mm": D("21.00")}
    assert by_type["valve"][0].quantity == 2
    assert [line.quantity for line in by_type["fitting"]] == [14, 14]
    assert "emitter" not in by_type and "injector" not in by_type
    assert all(line.rationale for line in lines)


def test_bom_waste_rate_must_be_explicit():
    with pytest.raises(MissingInputError):
        compute_bom(bom(installation_waste_rate=None))


def test_bom_separate_emitters():
    _, lines = compute_bom(bom(emitters_integrated=False, installation_waste_rate=D(0)))
    assert [line.quantity for line in lines if line.component_type == "emitter"] == [2324]


# --- Sprinkler ----------------------------------------------------------------------


def test_sprinkler_parametric():
    result = compute_sprinkler(
        SprinklerInput(
            sprinkler_count=20,
            sprinkler_flow_lph=D(500),
            spacing_along_m=D(10),
            spacing_between_m=D(10),
            sector_count=2,
        )
    )
    assert result.output("total_flow_m3h") == D("10.0000")
    assert result.output("application_rate_mm_per_h") == D("5.000")
    with pytest.raises(MissingInputError):
        compute_sprinkler(SprinklerInput(None, D(1), D(1), D(1), 1))


# --- Quotation ----------------------------------------------------------------------


def test_quote_rounding_and_unpriced_lines():
    result, totals = compute_quote(
        QuoteInput(
            "XAF",
            0,
            [
                QuoteLineInput("a", "Rouleaux", D(2), D("25000.4")),
                QuoteLineInput("b", "Conduite", D("735.5"), D(150)),
                QuoteLineInput("c", "Pompe", D(1), None),
            ],
        )
    )
    assert totals == {"a": D(50001), "b": D(110325), "c": None}
    assert result.output("subtotal") == D(160326)
    assert result.output("total") == D(160326)
    assert result.output("unpriced_line_count") == 1
    assert result.warnings


def test_quote_discount_and_tax_two_decimals():
    result, _ = compute_quote(
        QuoteInput(
            "EUR",
            2,
            [QuoteLineInput("a", "x", D(3), D("9.99"))],
            discount_amount=D("2.97"),
            tax_rate=D("0.2"),
        )
    )
    # 29.97 − 2.97 = 27.00 ; tax 5.40 ; total 32.40
    assert result.output("tax_amount") == D("5.40")
    assert result.output("total") == D("32.40")
    with pytest.raises(InvalidInputError):
        compute_quote(
            QuoteInput("EUR", 2, [QuoteLineInput("a", "x", D(1), D(1))], discount_amount=D(5))
        )
