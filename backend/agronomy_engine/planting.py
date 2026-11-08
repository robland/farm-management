"""Planting density and plant count (AGRONOMY_ENGINE.md §3, FR-032).

Distinguishes the theoretical density (from spacings) from the density that
is really plantable on the allocated area (alleys, paths, headlands).
"""

from dataclasses import asdict, dataclass
from decimal import Decimal

from agronomy_engine.errors import (
    InvalidInputError,
    MissingInputError,
    present,
    require,
    require_non_negative,
    require_positive,
)
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import M2_PER_HA, floor_int, q

SINGLE_ROW = "single_row"
BEDS = "beds"
COUNT_GAP_WARNING_RATE = Decimal("0.10")
AREA_GAP_WARNING_RATE = Decimal("0.05")


@dataclass(frozen=True)
class PlantingInput:
    row_spacing_m: Decimal | None
    plant_spacing_m: Decimal | None
    plants_per_hole: int | None
    allocated_area_m2: Decimal | None
    non_plantable_area_m2: Decimal | None
    layout: str = SINGLE_ROW
    plot_length_m: Decimal | None = None
    plot_width_m: Decimal | None = None
    headland_m: Decimal | None = None
    bed_width_m: Decimal | None = None
    path_width_m: Decimal | None = None
    rows_per_bed: int | None = None


def compute_planting(data: PlantingInput) -> CalculationResult:
    values = asdict(data)
    require(
        values,
        [
            "row_spacing_m",
            "plant_spacing_m",
            "plants_per_hole",
            "allocated_area_m2",
            "non_plantable_area_m2",
        ],
    )
    er = present(data.row_spacing_m, "row_spacing_m")
    ep = present(data.plant_spacing_m, "plant_spacing_m")
    k = present(data.plants_per_hole, "plants_per_hole")
    s = present(data.allocated_area_m2, "allocated_area_m2")
    snp = present(data.non_plantable_area_m2, "non_plantable_area_m2")
    for name in ("row_spacing_m", "plant_spacing_m", "plants_per_hole", "allocated_area_m2"):
        require_positive(name, values[name])
    require_non_negative("non_plantable_area_m2", snp)
    if snp >= s:
        raise InvalidInputError(
            "non_plantable_area_m2", "doit être inférieure à la surface allouée"
        )
    if data.layout not in {SINGLE_ROW, BEDS}:
        raise InvalidInputError("layout", "disposition inconnue")

    assumptions: list[str] = []
    warnings: list[str] = []
    density_th = Decimal(k) / (er * ep)
    plantable = s - snp
    # Multiply before dividing: floor(k × Sp / (Er × Ep)) avoids losing a plant to the
    # rounding of a repeating density (e.g. 1 / 0.75 × 750 = 999.999…).
    count_th = floor_int(Decimal(k) * plantable / (er * ep))
    outputs = {
        "theoretical_density_per_m2": Quantity(q(density_th), "plants/m2"),
        "theoretical_density_per_ha": Quantity(q(density_th * M2_PER_HA, 2), "plants/ha"),
        "plantable_area_m2": Quantity(q(plantable), "m2"),
        "theoretical_plant_count": Quantity(count_th, "plants"),
    }
    formula = "Dth = k / (Er × Ep) ; Sp = S − Snp ; Nth = floor(Dth × Sp)"
    details: dict[str, object] = {}

    geometric = data.plot_length_m is not None or data.plot_width_m is not None
    if geometric:
        require(
            values,
            ["plot_length_m", "plot_width_m", "headland_m"],
            "nécessaires au calcul géométrique",
        )
        length = present(data.plot_length_m, "plot_length_m")
        width = present(data.plot_width_m, "plot_width_m")
        border = present(data.headland_m, "headland_m")
        require_positive("plot_length_m", length)
        require_positive("plot_width_m", width)
        require_non_negative("headland_m", border)
        usable_length = length - 2 * border
        usable_width = width - 2 * border
        if usable_length <= 0 or usable_width <= 0:
            raise InvalidInputError("headland_m", "les bordures dépassent les dimensions")
        if data.layout == BEDS:
            require(
                values,
                ["bed_width_m", "path_width_m", "rows_per_bed"],
                "nécessaires pour une disposition en planches",
            )
            bed = present(data.bed_width_m, "bed_width_m")
            path = present(data.path_width_m, "path_width_m")
            rows_per_bed = present(data.rows_per_bed, "rows_per_bed")
            require_positive("bed_width_m", bed)
            require_non_negative("path_width_m", path)
            require_positive("rows_per_bed", rows_per_bed)
            if (rows_per_bed - 1) * er > bed:
                raise InvalidInputError("rows_per_bed", "trop de lignes pour la largeur de planche")
            beds = floor_int((usable_width + path) / (bed + path))
            rows = beds * rows_per_bed
            details["beds"] = beds
            formula += (
                " ; planches = floor((Wu + allée) / (planche + allée))"
                " ; lignes = planches × lignes/planche"
            )
        else:
            rows = floor_int(usable_width / er) + 1
            formula += " ; lignes = floor(Wu / Er) + 1"
        per_row = floor_int(usable_length / ep) + 1
        count_real = rows * per_row * k
        formula += (
            " ; plants/ligne = floor(Lu / Ep) + 1 ; Nr = lignes × plants/ligne × k ; Dr = Nr / S"
        )
        assumptions += [
            "Disposition rectangulaire, lignes parallèles à la longueur de la parcelle.",
            "Un plant en début et en fin de ligne utile ; bordure identique sur les quatre côtés.",
        ]
        details.update(
            rows=rows,
            plants_per_row=per_row,
            usable_length_m=str(usable_length),
            usable_width_m=str(usable_width),
        )
        declared = length * width
        if abs(declared - s) / s > AREA_GAP_WARNING_RATE:
            warnings.append(
                f"Longueur × largeur ({q(declared, 2)} m²) diffère de plus de 5 % "
                f"de la surface allouée ({q(s, 2)} m²)."
            )
        if count_th and abs(Decimal(count_real - count_th)) / count_th > COUNT_GAP_WARNING_RATE:
            warnings.append(
                f"Nombre de plants réel ({count_real}) et théorique ({count_th}) "
                "diffèrent de plus de 10 %."
            )
        basis = "geometric"
    else:
        count_real = count_th
        assumptions.append(
            "Sans dimensions de parcelle, les plants sont supposés répartis uniformément "
            "sur la surface plantable (Nr = Nth)."
        )
        basis = "theoretical"

    if count_real <= 0:
        raise InvalidInputError("allocated_area_m2", "surface insuffisante pour un plant")
    outputs.update(
        plant_count=Quantity(count_real, "plants"),
        plant_count_basis=Quantity(basis),
        real_density_per_m2=Quantity(q(Decimal(count_real) / s), "plants/m2"),
        real_density_on_plantable_per_m2=Quantity(q(Decimal(count_real) / plantable), "plants/m2"),
        real_density_per_ha=Quantity(q(Decimal(count_real) / s * M2_PER_HA, 2), "plants/ha"),
    )
    inputs = {
        "row_spacing_m": Quantity(er, "m"),
        "plant_spacing_m": Quantity(ep, "m"),
        "plants_per_hole": Quantity(k, "plants/poquet"),
        "allocated_area_m2": Quantity(s, "m2"),
        "non_plantable_area_m2": Quantity(snp, "m2"),
        "layout": Quantity(data.layout),
    }
    for name, unit in (
        ("plot_length_m", "m"),
        ("plot_width_m", "m"),
        ("headland_m", "m"),
        ("bed_width_m", "m"),
        ("path_width_m", "m"),
    ):
        if values[name] is not None:
            inputs[name] = Quantity(values[name], unit)
    if data.rows_per_bed is not None:
        inputs["rows_per_bed"] = Quantity(data.rows_per_bed, "lignes")
    return CalculationResult(
        calc_type="planting.density",
        inputs=inputs,
        outputs=outputs,
        formula=formula,
        assumptions=assumptions,
        warnings=warnings,
        details=details,
    )


__all__ = ["BEDS", "SINGLE_ROW", "MissingInputError", "PlantingInput", "compute_planting"]
