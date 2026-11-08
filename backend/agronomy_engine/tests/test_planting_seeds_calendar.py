"""Reference cases computed by hand (values are arithmetic examples, not agronomic advice)."""

from datetime import date
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agronomy_engine.crop_calendar import CalendarInput, PhaseSpec, ProgramItem, compute_calendar
from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.planting import BEDS, PlantingInput, compute_planting
from agronomy_engine.seeds import TRANSPLANTING, SeedInput, compute_seeds
from agronomy_engine.units import bar_to_m_head, ceil_int, floor_int, ha_to_m2, m2_to_ha


def planting(**overrides):
    base = dict(
        row_spacing_m=D("1.5"),
        plant_spacing_m=D("0.5"),
        plants_per_hole=1,
        allocated_area_m2=D(1000),
        non_plantable_area_m2=D(0),
    )
    return PlantingInput(**{**base, **overrides})


# --- Units --------------------------------------------------------------------------


def test_unit_conversions():
    assert m2_to_ha(D(25000)) == D("2.5")
    assert ha_to_m2(D("0.1")) == D(1000)
    assert floor_int(D("13.99")) == 13 and ceil_int(D("13.01")) == 14
    assert round(bar_to_m_head(D(1)), 3) == D("10.197")


# --- Planting -----------------------------------------------------------------------


def test_theoretical_density_without_geometry():
    result = compute_planting(planting())
    assert result.output("theoretical_density_per_m2") == D("1.3333")
    assert result.output("theoretical_plant_count") == 1333
    assert result.output("plant_count") == 1333
    assert result.output("plant_count_basis") == "theoretical"
    assert result.assumptions  # the uniform distribution assumption is stated


def test_non_plantable_area_reduces_real_density():
    result = compute_planting(planting(non_plantable_area_m2=D(250)))
    assert result.output("plantable_area_m2") == D("750.0000")
    assert result.output("plant_count") == 1000
    assert result.output("real_density_per_m2") == D("1.0000")  # on gross area
    assert result.output("real_density_on_plantable_per_m2") == D("1.3333")
    assert result.output("theoretical_density_per_m2") == D("1.3333")


def test_geometric_single_rows_50x20():
    result = compute_planting(planting(plot_length_m=D(50), plot_width_m=D(20), headland_m=D(0)))
    # rows = floor(20/1.5)+1 = 14 ; plants/row = floor(50/0.5)+1 = 101
    assert result.details["rows"] == 14 and result.details["plants_per_row"] == 101
    assert result.output("plant_count") == 1414
    assert result.output("real_density_per_m2") == D("1.4140")
    assert result.warnings == []


def test_geometric_with_headland():
    result = compute_planting(planting(plot_length_m=D(50), plot_width_m=D(20), headland_m=D(1)))
    # Lu = 48, Wu = 18 -> rows 13, plants/row 97
    assert result.output("plant_count") == 13 * 97


def test_geometric_beds():
    result = compute_planting(
        planting(
            row_spacing_m=D("0.6"),
            plant_spacing_m=D("0.4"),
            layout=BEDS,
            plot_length_m=D(50),
            plot_width_m=D(20),
            headland_m=D(0),
            bed_width_m=D("1.2"),
            path_width_m=D("0.5"),
            rows_per_bed=2,
        )
    )
    # beds = floor(20.5 / 1.7) = 12 ; rows = 24 ; plants/row = floor(50/0.4)+1 = 126
    assert result.details["beds"] == 12
    assert result.output("plant_count") == 24 * 126


def test_warnings_on_area_and_count_gaps():
    result = compute_planting(planting(plot_length_m=D(10), plot_width_m=D(10), headland_m=D(0)))
    assert len(result.warnings) == 2


@pytest.mark.parametrize(
    "field",
    [
        "row_spacing_m",
        "plant_spacing_m",
        "plants_per_hole",
        "allocated_area_m2",
        "non_plantable_area_m2",
    ],
)
def test_missing_planting_inputs(field):
    with pytest.raises(MissingInputError) as exc:
        compute_planting(planting(**{field: None}))
    assert exc.value.fields == [field]


def test_geometry_requires_explicit_headland_and_bed_parameters():
    with pytest.raises(MissingInputError) as exc:
        compute_planting(planting(plot_length_m=D(50), plot_width_m=D(20)))
    assert exc.value.fields == ["headland_m"]
    with pytest.raises(MissingInputError):
        compute_planting(
            planting(plot_length_m=D(50), plot_width_m=D(20), headland_m=D(0), layout=BEDS)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"row_spacing_m": D(0)},
        {"plant_spacing_m": D("-1")},
        {"non_plantable_area_m2": D(1000)},
        {"plot_length_m": D(4), "plot_width_m": D(4), "headland_m": D(2)},
        {"layout": "spiral"},
    ],
)
def test_invalid_planting_inputs(overrides):
    with pytest.raises(InvalidInputError):
        compute_planting(planting(**overrides))


spacing = st.decimals(min_value=D("0.1"), max_value=D(5), places=2)


@given(er=spacing, ep=spacing, factor=st.decimals(min_value=D("1.01"), max_value=D(3), places=2))
def test_density_decreases_when_spacing_increases(er, ep, factor):
    narrow = compute_planting(planting(row_spacing_m=er, plant_spacing_m=ep))
    wide = compute_planting(planting(row_spacing_m=er * factor, plant_spacing_m=ep))
    assert wide.output("theoretical_density_per_m2") <= narrow.output("theoretical_density_per_m2")
    assert wide.output("plant_count") <= narrow.output("plant_count")


@given(er=spacing, ep=spacing, area=st.integers(min_value=50, max_value=50_000))
def test_plant_count_never_exceeds_theoretical_capacity(er, ep, area):
    result = compute_planting(
        planting(row_spacing_m=er, plant_spacing_m=ep, allocated_area_m2=D(area))
    )
    assert 0 < result.output("plant_count") <= D(area) / (er * ep)


# --- Seeds --------------------------------------------------------------------------


def seeds(**overrides):
    base = dict(
        plant_count=1414,
        plants_per_hole=1,
        seeds_per_hole=2,
        germination_rate=D("0.8"),
        safety_margin_rate=D("0.1"),
        seeds_per_gram=D(25),
        seed_package_size_g=D(50),
    )
    return SeedInput(**{**base, **overrides})


def test_direct_seeding_reference():
    result = compute_seeds(seeds())
    # ceil(1414 × 2 × 1.1 / 0.8) = ceil(3888.5) = 3889 ; 3889 / 25 = 155.56 g ; 4 sachets
    assert result.output("seed_count") == 3889
    assert result.output("seed_mass_g") == D("155.56")
    assert result.output("packages") == 4


def test_transplanting_reference_with_thousand_seed_weight():
    result = compute_seeds(
        seeds(
            plant_count=1000,
            seeds_per_hole=1,
            germination_rate=D("0.9"),
            safety_margin_rate=D("0.05"),
            planting_method=TRANSPLANTING,
            nursery_success_rate=D("0.95"),
            seeds_per_gram=None,
            thousand_seed_weight_g=D(250),
            seed_package_size_g=None,
        )
    )
    # ceil(1000 × 1.05 / (0.9 × 0.95)) = ceil(1228.07) = 1229 ; 1229 × 250 / 1000 = 307.25 g
    assert result.output("seed_count") == 1229
    assert result.output("seed_mass_g") == D("307.25")
    assert "packages" not in result.outputs


def test_direct_seeding_with_several_plants_per_hole():
    result = compute_seeds(
        seeds(
            plant_count=1001,
            plants_per_hole=2,
            seeds_per_hole=3,
            germination_rate=D(1),
            safety_margin_rate=D(0),
        )
    )
    assert result.output("sowing_points") == 501  # ceil(1001 / 2)
    assert result.output("seed_count") == 1503


def test_seed_missing_inputs_are_all_reported():
    with pytest.raises(MissingInputError) as exc:
        compute_seeds(seeds(germination_rate=None, seeds_per_gram=None, safety_margin_rate=None))
    assert set(exc.value.fields) == {
        "germination_rate",
        "safety_margin_rate",
        "seeds_per_gram|thousand_seed_weight_g",
    }
    with pytest.raises(MissingInputError) as exc:
        compute_seeds(seeds(planting_method=TRANSPLANTING))
    assert exc.value.fields == ["nursery_success_rate"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"germination_rate": D("1.2")},
        {"germination_rate": D(0)},
        {"safety_margin_rate": D("-0.1")},
        {"planting_method": "magic"},
    ],
)
def test_invalid_seed_inputs(overrides):
    with pytest.raises(InvalidInputError):
        compute_seeds(seeds(**overrides))


@given(rate=st.decimals(min_value=D("0.3"), max_value=D("0.99"), places=2))
def test_lower_germination_needs_more_seeds(rate):
    assert compute_seeds(seeds(germination_rate=rate)).output("seed_count") >= compute_seeds(
        seeds(germination_rate=D(1))
    ).output("seed_count")


# --- Calendar -----------------------------------------------------------------------


def calendar(**overrides):
    base = dict(
        start_date=date(2026, 1, 1),
        phases=[
            PhaseSpec("soil_preparation", 7),
            PhaseSpec("sowing", 1),
            PhaseSpec("vegetative", 30),
        ],
    )
    return CalendarInput(**{**base, **overrides})


def test_phases_are_chained():
    result, phases, proposals = compute_calendar(calendar())
    assert [(p.code, p.start_date, p.end_date) for p in phases] == [
        ("soil_preparation", date(2026, 1, 1), date(2026, 1, 7)),
        ("sowing", date(2026, 1, 8), date(2026, 1, 8)),
        ("vegetative", date(2026, 1, 9), date(2026, 2, 7)),
    ]
    assert result.output("cycle_duration_days") == 38
    # Only operational phases become task proposals.
    assert [p.source_ref for p in proposals] == ["phase:soil_preparation", "phase:sowing"]


def test_program_items_are_positioned():
    _, _, proposals = compute_calendar(
        calendar(
            program=[
                ProgramItem(
                    "fert:1", "fertilization", "Apport 1", phase_code="vegetative", offset_days=10
                ),
                ProgramItem("obs:1", "other", "Contrôle", offset_days=2),
            ]
        )
    )
    by_ref = {p.source_ref: p for p in proposals}
    assert by_ref["fert:1"].planned_start_date == date(2026, 1, 19)
    assert by_ref["obs:1"].planned_start_date == date(2026, 1, 3)


def test_program_item_outside_cycle_warns():
    result, _, _ = compute_calendar(
        calendar(program=[ProgramItem("late", "other", "Tardif", offset_days=100)])
    )
    assert result.warnings


def test_calendar_missing_and_invalid():
    with pytest.raises(MissingInputError):
        compute_calendar(calendar(start_date=None))
    with pytest.raises(MissingInputError) as exc:
        compute_calendar(calendar(phases=[PhaseSpec("sowing", None)]))
    assert exc.value.fields == ["phase.sowing.duration_days"]
    with pytest.raises(InvalidInputError):
        compute_calendar(calendar(phases=[PhaseSpec("sowing", 0)]))
    with pytest.raises(InvalidInputError):
        compute_calendar(calendar(phases=[PhaseSpec("sowing", 1), PhaseSpec("sowing", 2)]))
    with pytest.raises(InvalidInputError):
        compute_calendar(calendar(program=[ProgramItem("x", "other", "x", phase_code="absent")]))


def test_engine_is_deterministic():
    assert compute_planting(planting()).to_dict() == compute_planting(planting()).to_dict()
