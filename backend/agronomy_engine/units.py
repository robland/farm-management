"""Explicit unit conversions (NFR-007). All values are Decimal; no implicit conversion."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

M2_PER_HA = Decimal(10_000)
L_PER_M3 = Decimal(1_000)
G_PER_KG = Decimal(1_000)
SECONDS_PER_HOUR = Decimal(3_600)
# 1 bar = 100 000 Pa; head (m) = p / (rho * g) with rho = 1000 kg/m3, g = 9.80665 m/s2.
GRAVITY_M_S2 = Decimal("9.80665")
WATER_DENSITY_KG_M3 = Decimal(1_000)
M_HEAD_PER_BAR = Decimal(100_000) / (WATER_DENSITY_KG_M3 * GRAVITY_M_S2)


def m2_to_ha(area_m2: Decimal) -> Decimal:
    return area_m2 / M2_PER_HA


def ha_to_m2(area_ha: Decimal) -> Decimal:
    return area_ha * M2_PER_HA


def lph_to_m3h(flow_lph: Decimal) -> Decimal:
    return flow_lph / L_PER_M3


def m3h_to_m3s(flow_m3h: Decimal) -> Decimal:
    return flow_m3h / SECONDS_PER_HOUR


def bar_to_m_head(pressure_bar: Decimal) -> Decimal:
    return pressure_bar * M_HEAD_PER_BAR


def mm_on_m2_to_l(depth_mm: Decimal, area_m2: Decimal) -> Decimal:
    """1 mm of water over 1 m² equals 1 litre."""
    return depth_mm * area_m2


def floor_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def q(value: Decimal, places: int = 4) -> Decimal:
    """Quantize for presentation/storage; intermediate calculations keep full precision."""
    return value.quantize(Decimal(1).scaleb(-places))
