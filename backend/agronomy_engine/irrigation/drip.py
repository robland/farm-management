"""Drip irrigation sizing (AGRONOMY_ENGINE.md §5, FR-041).

Keeps the daily water VOLUME (L/day, m³/day) strictly separate from the
instantaneous FLOW (L/h, m³/h). Head losses, elevation and filtration are
included only when provided; anything not provided is listed as not taken
into account.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from agronomy_engine.errors import (
    InvalidInputError,
    MissingInputError,
    present,
    require_positive,
    require_rate,
)
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import (
    GRAVITY_M_S2,
    L_PER_M3,
    WATER_DENSITY_KG_M3,
    bar_to_m_head,
    ceil_int,
    floor_int,
    lph_to_m3h,
    m3h_to_m3s,
    mm_on_m2_to_l,
    q,
)

# Hazen-Williams, SI form: hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87), Q in m³/s, D in m.
HW_COEFFICIENT = Decimal("10.67")
HW_FLOW_EXPONENT = Decimal("1.852")
HW_DIAMETER_EXPONENT = Decimal("4.87")

MAIN, SUBMAIN, LATERAL = "main", "submain", "lateral"


@dataclass(frozen=True)
class PipeSegment:
    role: str  # main | submain | lateral
    length_m: Decimal
    inner_diameter_mm: Decimal
    hazen_williams_c: Decimal
    outlets: int | None = None  # outlets along the pipe (Christiansen factor)


@dataclass(frozen=True)
class DripInput:
    lateral_count: int | None
    lateral_length_m: Decimal | None
    lateral_spacing_m: Decimal | None
    emitter_spacing_m: Decimal | None
    emitter_flow_lph: Decimal | None
    operating_pressure_bar: Decimal | None
    # Water need: all or nothing.
    irrigated_area_m2: Decimal | None = None
    et0_mm_per_day: Decimal | None = None
    kc: Decimal | None = None
    application_efficiency_rate: Decimal | None = None
    # Sectors: from the source capacity, or chosen by the user.
    source_max_flow_m3h: Decimal | None = None
    sector_count: int | None = None
    max_irrigation_hours_per_day: Decimal | None = None
    # Pumping head components (optional, included when provided).
    static_lift_m: Decimal | None = None
    elevation_difference_m: Decimal | None = None
    filter_head_loss_m: Decimal | None = None
    fittings_loss_rate: Decimal | None = None
    pump_efficiency_rate: Decimal | None = None
    segments: list[PipeSegment] = field(default_factory=list)


def christiansen_factor(outlets: int) -> Decimal:
    """F = 1/(m+1) + 1/(2N) + sqrt(m-1)/(6N²) with m = 1.852 (multiple-outlet pipe)."""
    if outlets < 1:
        raise InvalidInputError("outlets", "au moins une sortie")
    if outlets == 1:
        return Decimal(1)
    m, n = HW_FLOW_EXPONENT, Decimal(outlets)
    return 1 / (m + 1) + 1 / (2 * n) + (m - 1).sqrt() / (6 * n * n)


def hazen_williams_loss_m(
    flow_m3s: Decimal, length_m: Decimal, diameter_m: Decimal, c: Decimal
) -> Decimal:
    return (
        HW_COEFFICIENT
        * length_m
        * flow_m3s**HW_FLOW_EXPONENT
        / (c**HW_FLOW_EXPONENT * diameter_m**HW_DIAMETER_EXPONENT)
    )


def compute_drip(data: DripInput) -> CalculationResult:
    core = {
        "lateral_count": data.lateral_count,
        "lateral_length_m": data.lateral_length_m,
        "lateral_spacing_m": data.lateral_spacing_m,
        "emitter_spacing_m": data.emitter_spacing_m,
        "emitter_flow_lph": data.emitter_flow_lph,
        "operating_pressure_bar": data.operating_pressure_bar,
    }
    missing = [name for name, value in core.items() if value is None]
    water = {
        "irrigated_area_m2": data.irrigated_area_m2,
        "et0_mm_per_day": data.et0_mm_per_day,
        "kc": data.kc,
        "application_efficiency_rate": data.application_efficiency_rate,
    }
    provided_water = [n for n, v in water.items() if v is not None]
    if provided_water:
        missing += [n for n, v in water.items() if v is None]
    if data.source_max_flow_m3h is None and data.sector_count is None:
        missing.append("source_max_flow_m3h|sector_count")
    if missing:
        raise MissingInputError(missing)

    laterals = present(data.lateral_count, "lateral_count")
    lateral_length = present(data.lateral_length_m, "lateral_length_m")
    lateral_spacing = present(data.lateral_spacing_m, "lateral_spacing_m")
    emitter_spacing = present(data.emitter_spacing_m, "emitter_spacing_m")
    emitter_flow = present(data.emitter_flow_lph, "emitter_flow_lph")
    pressure = present(data.operating_pressure_bar, "operating_pressure_bar")
    for name, value in core.items():
        require_positive(name, value)  # type: ignore[arg-type]

    inputs: dict[str, Quantity] = {
        "lateral_count": Quantity(laterals, "rampes"),
        "lateral_length_m": Quantity(lateral_length, "m"),
        "lateral_spacing_m": Quantity(lateral_spacing, "m"),
        "emitter_spacing_m": Quantity(emitter_spacing, "m"),
        "emitter_flow_lph": Quantity(emitter_flow, "L/h"),
        "operating_pressure_bar": Quantity(pressure, "bar"),
    }
    assumptions = [
        "Premier goutteur à une demi-espacement du début de rampe.",
        "Débit des goutteurs constant (variations de pression non modélisées).",
    ]
    not_considered: list[str] = []
    warnings: list[str] = []
    details: dict[str, object] = {}

    emitters_per_lateral = floor_int(lateral_length / emitter_spacing)
    if emitters_per_lateral < 1:
        raise InvalidInputError("lateral_length_m", "plus courte que l'espacement des goutteurs")
    emitter_count = emitters_per_lateral * laterals
    lateral_flow_lph = emitters_per_lateral * emitter_flow
    total_flow_lph = emitter_count * emitter_flow
    total_flow_m3h = lph_to_m3h(total_flow_lph)
    application_rate = emitter_flow / (emitter_spacing * lateral_spacing)
    outputs: dict[str, Quantity] = {
        "emitters_per_lateral": Quantity(emitters_per_lateral, "goutteurs"),
        "emitter_count": Quantity(emitter_count, "goutteurs"),
        "lateral_flow_lph": Quantity(q(lateral_flow_lph, 2), "L/h"),
        "total_flow_lph": Quantity(q(total_flow_lph, 2), "L/h"),
        "total_flow_m3h": Quantity(q(total_flow_m3h, 4), "m3/h"),
        "application_rate_mm_per_h": Quantity(q(application_rate, 3), "mm/h"),
    }
    formula = "ne = floor(Lr / eg) ; NE = ne × Nr ; Qt (L/h) = NE × qg ; I (mm/h) = qg / (eg × er)"

    # Sectors.
    if data.source_max_flow_m3h is not None:
        require_positive("source_max_flow_m3h", data.source_max_flow_m3h)
        sectors = ceil_int(total_flow_m3h / data.source_max_flow_m3h)
        inputs["source_max_flow_m3h"] = Quantity(data.source_max_flow_m3h, "m3/h")
        formula += " ; secteurs = ceil(Qt / Qsource)"
        if data.sector_count is not None and data.sector_count < sectors:
            raise InvalidInputError(
                "sector_count", f"au moins {sectors} secteurs requis par la source"
            )
        if data.sector_count is not None:
            sectors = data.sector_count
    else:
        sectors = present(data.sector_count, "sector_count")
        require_positive("sector_count", sectors)
        assumptions.append(
            "Nombre de secteurs choisi par l'utilisateur (capacité de la source non renseignée)."
        )
    if sectors > laterals:
        raise InvalidInputError("sector_count", "plus de secteurs que de rampes")
    inputs["sector_count"] = Quantity(sectors, "secteurs")
    sector_flow_m3h = total_flow_m3h / sectors
    outputs["sector_count"] = Quantity(sectors, "secteurs")
    outputs["sector_flow_m3h"] = Quantity(q(sector_flow_m3h, 4), "m3/h")
    formula += " ; Qs = Qt / secteurs"

    # Daily water need (volume, not flow).
    if provided_water:
        area = present(data.irrigated_area_m2, "irrigated_area_m2")
        et0 = present(data.et0_mm_per_day, "et0_mm_per_day")
        kc = present(data.kc, "kc")
        efficiency = present(data.application_efficiency_rate, "application_efficiency_rate")
        require_positive("irrigated_area_m2", area)
        require_positive("et0_mm_per_day", et0)
        require_positive("kc", kc)
        require_rate("application_efficiency_rate", efficiency)
        etc = kc * et0
        net_l = mm_on_m2_to_l(etc, area)
        gross_l = net_l / efficiency
        hours_per_sector = (gross_l / sectors) / (sector_flow_m3h * L_PER_M3)
        total_hours = hours_per_sector * sectors
        inputs.update(
            irrigated_area_m2=Quantity(area, "m2"),
            et0_mm_per_day=Quantity(et0, "mm/j"),
            kc=Quantity(kc, "ratio"),
            application_efficiency_rate=Quantity(efficiency, "ratio"),
        )
        outputs.update(
            etc_mm_per_day=Quantity(q(etc, 3), "mm/j"),
            net_daily_volume_l=Quantity(q(net_l, 1), "L/j"),
            gross_daily_volume_l=Quantity(q(gross_l, 1), "L/j"),
            gross_daily_volume_m3=Quantity(q(gross_l / L_PER_M3, 3), "m3/j"),
            irrigation_hours_per_sector=Quantity(q(hours_per_sector, 2), "h/j"),
            total_irrigation_hours_per_day=Quantity(q(total_hours, 2), "h/j"),
        )
        formula += (
            " ; ETc = Kc × ET0 ; Vnet (L/j) = ETc × S ; Vbrut = Vnet / Ea ; "
            "t (h) = (Vbrut / secteurs) / Qs"
        )
        assumptions.append("1 mm d'eau sur 1 m² = 1 L ; besoin uniforme sur la surface irriguée.")
        if data.max_irrigation_hours_per_day is not None:
            inputs["max_irrigation_hours_per_day"] = Quantity(
                data.max_irrigation_hours_per_day, "h/j"
            )
            if total_hours > data.max_irrigation_hours_per_day:
                warnings.append(
                    f"Durée d'arrosage totale ({q(total_hours, 2)} h/j) supérieure au maximum "
                    f"disponible ({data.max_irrigation_hours_per_day} h/j)."
                )
    else:
        not_considered.append("Besoin en eau journalier (ET0, Kc, efficience, surface)")

    # Friction losses along the critical path (segments considered in series).
    friction = Decimal(0)
    if data.segments:
        segment_details = []
        for index, segment in enumerate(data.segments):
            if segment.role not in {MAIN, SUBMAIN, LATERAL}:
                raise InvalidInputError(f"segments.{index}.role", "rôle inconnu")
            for name in ("length_m", "inner_diameter_mm", "hazen_williams_c"):
                require_positive(f"segments.{index}.{name}", getattr(segment, name))
            if segment.role == LATERAL:
                flow_m3h = lph_to_m3h(lateral_flow_lph)
                outlets = segment.outlets or emitters_per_lateral
            else:
                flow_m3h = sector_flow_m3h
                if segment.role == SUBMAIN and segment.outlets is None:
                    raise MissingInputError(
                        [f"segments.{index}.outlets"],
                        "nombre de rampes alimentées par le porte-rampe",
                    )
                outlets = segment.outlets or 1
            loss = hazen_williams_loss_m(
                m3h_to_m3s(flow_m3h),
                segment.length_m,
                segment.inner_diameter_mm / 1000,
                segment.hazen_williams_c,
            )
            factor = christiansen_factor(outlets)
            friction += loss * factor
            segment_details.append(
                {
                    "role": segment.role,
                    "flow_m3h": str(q(flow_m3h, 4)),
                    "outlets": outlets,
                    "christiansen_factor": str(q(factor, 4)),
                    "head_loss_m": str(q(loss * factor, 3)),
                }
            )
        details["segments"] = segment_details
        formula += " ; hf = 10,67·L·Q^1,852 / (C^1,852·D^4,87) × F(Christiansen)"
        assumptions.append(
            "Segments considérés en série sur le chemin hydraulique le plus défavorable."
        )
        outputs["friction_loss_m"] = Quantity(q(friction, 3), "m")
    else:
        not_considered.append("Pertes de charge linéaires (conduites non renseignées)")

    fittings = Decimal(0)
    if data.fittings_loss_rate is not None:
        fittings = friction * data.fittings_loss_rate
        inputs["fittings_loss_rate"] = Quantity(data.fittings_loss_rate, "ratio")
    elif data.segments:
        not_considered.append("Pertes singulières (raccords, vannes)")
    pressure_head = bar_to_m_head(pressure)
    head = pressure_head + friction + fittings
    for name, label in (
        ("static_lift_m", "Hauteur d'aspiration / refoulement"),
        ("elevation_difference_m", "Dénivelé"),
        ("filter_head_loss_m", "Perte de charge de filtration"),
    ):
        value = getattr(data, name)
        if value is None:
            not_considered.append(label)
        else:
            head += value
            inputs[name] = Quantity(value, "m")
    outputs["pressure_head_m"] = Quantity(q(pressure_head, 3), "m")
    outputs["total_dynamic_head_m"] = Quantity(q(head, 3), "m")
    formula += " ; HMT = Hstatique + ΔZ + Σhf × (1 + k_sing) + h_filtre + P × 10,197"
    if head <= 0:
        warnings.append("Hauteur manométrique totale nulle ou négative : vérifier le dénivelé.")

    hydraulic_w = WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * m3h_to_m3s(sector_flow_m3h) * head
    outputs["hydraulic_power_w"] = Quantity(q(hydraulic_w, 1), "W")
    formula += " ; Ph (W) = ρ·g·Qs·HMT"
    if data.pump_efficiency_rate is not None:
        require_rate("pump_efficiency_rate", data.pump_efficiency_rate)
        inputs["pump_efficiency_rate"] = Quantity(data.pump_efficiency_rate, "ratio")
        absorbed = hydraulic_w / data.pump_efficiency_rate
        outputs["absorbed_power_w"] = Quantity(q(absorbed, 1), "W")
        outputs["absorbed_power_kw"] = Quantity(q(absorbed / 1000, 3), "kW")
        formula += " ; Pa = Ph / η"
    else:
        not_considered.append("Rendement de la pompe (puissance absorbée non calculée)")
    assumptions.append("Masse volumique de l'eau 1000 kg/m³ ; g = 9,80665 m/s².")
    assumptions.append(
        "Pompage dimensionné sur le débit d'un secteur (secteurs irrigués successivement)."
    )
    details["not_considered"] = not_considered
    return CalculationResult(
        calc_type="irrigation.drip",
        inputs=inputs,
        outputs=outputs,
        formula=formula,
        assumptions=assumptions,
        warnings=warnings,
        details=details,
    )
