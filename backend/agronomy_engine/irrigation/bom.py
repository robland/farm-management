"""Bill of materials for a drip design (AGRONOMY_ENGINE.md §5.3, FR-042).

Each line carries the rationale of its quantity. The installation waste
rate is an explicit user input, never imposed.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from agronomy_engine.errors import MissingInputError, require_non_negative, require_positive
from agronomy_engine.irrigation.drip import MAIN, SUBMAIN, PipeSegment
from agronomy_engine.result import CalculationResult, Quantity
from agronomy_engine.units import ceil_int, q


@dataclass(frozen=True)
class BomInput:
    lateral_count: int
    lateral_length_m: Decimal
    emitter_count: int
    sector_count: int
    installation_waste_rate: Decimal | None
    emitters_integrated: bool = True
    dripline_roll_length_m: Decimal | None = None
    segments: list[PipeSegment] = field(default_factory=list)
    filter_count: int = 0
    pressure_regulator_count: int = 0
    include_pump: bool = False
    include_fertilizer_injector: bool = False


@dataclass(frozen=True)
class BomLineProposal:
    component_type: str
    description: str
    quantity: Decimal
    unit: str
    rationale: str
    spec: dict[str, str] = field(default_factory=dict)


def compute_bom(data: BomInput) -> tuple[CalculationResult, list[BomLineProposal]]:
    if data.installation_waste_rate is None:
        raise MissingInputError(
            ["installation_waste_rate"], "à saisir explicitement (0 si aucune perte prévue)"
        )
    waste = data.installation_waste_rate
    require_non_negative("installation_waste_rate", waste)
    require_positive("lateral_count", data.lateral_count)
    require_positive("lateral_length_m", data.lateral_length_m)
    factor = 1 + waste
    lines: list[BomLineProposal] = []

    dripline_m = Decimal(data.lateral_count) * data.lateral_length_m * factor
    if data.dripline_roll_length_m is not None:
        require_positive("dripline_roll_length_m", data.dripline_roll_length_m)
        rolls = ceil_int(dripline_m / data.dripline_roll_length_m)
        lines.append(
            BomLineProposal(
                "dripline",
                "Rampes de goutte-à-goutte",
                Decimal(rolls),
                "roll",
                f"ceil({data.lateral_count} rampes × {data.lateral_length_m} m × (1 + {waste}) "
                f"/ {data.dripline_roll_length_m} m par rouleau)",
                {"roll_length_m": str(data.dripline_roll_length_m)},
            )
        )
    else:
        lines.append(
            BomLineProposal(
                "dripline",
                "Rampes de goutte-à-goutte",
                q(dripline_m, 2),
                "m",
                f"{data.lateral_count} rampes × {data.lateral_length_m} m × (1 + {waste})",
            )
        )
    if not data.emitters_integrated:
        lines.append(
            BomLineProposal(
                "emitter",
                "Goutteurs",
                Decimal(ceil_int(Decimal(data.emitter_count) * factor)),
                "piece",
                f"ceil({data.emitter_count} goutteurs × (1 + {waste}))",
            )
        )

    by_pipe: dict[tuple[str, Decimal], Decimal] = {}
    for segment in data.segments:
        if segment.role in {MAIN, SUBMAIN}:
            key = (segment.role, segment.inner_diameter_mm)
            by_pipe[key] = by_pipe.get(key, Decimal(0)) + segment.length_m
    for (role, diameter), length in sorted(by_pipe.items()):
        label = "Conduite principale" if role == MAIN else "Porte-rampe"
        lines.append(
            BomLineProposal(
                "pipe",
                f"{label} Ø{diameter} mm",
                q(length * factor, 2),
                "m",
                f"Σ longueurs {role} ({length} m) × (1 + {waste})",
                {"role": role, "inner_diameter_mm": str(diameter)},
            )
        )

    count_lines = [
        ("fitting", "Prises de rampe (raccords de départ)", data.lateral_count, "Une par rampe"),
        ("fitting", "Bouchons de fin de rampe", data.lateral_count, "Un par rampe"),
        ("valve", "Vannes de secteur", data.sector_count, "Une par secteur"),
        ("filter", "Filtres", data.filter_count, "Nombre saisi"),
        ("regulator", "Régulateurs de pression", data.pressure_regulator_count, "Nombre saisi"),
        ("pump", "Pompe", 1 if data.include_pump else 0, "Option pompe"),
        (
            "injector",
            "Injecteur d'engrais",
            1 if data.include_fertilizer_injector else 0,
            "Option fertigation",
        ),
    ]
    for component, description, count, rationale in count_lines:
        if count > 0:
            lines.append(
                BomLineProposal(component, description, Decimal(count), "piece", rationale)
            )

    result = CalculationResult(
        calc_type="irrigation.bom",
        inputs={
            "lateral_count": Quantity(data.lateral_count, "rampes"),
            "lateral_length_m": Quantity(data.lateral_length_m, "m"),
            "emitter_count": Quantity(data.emitter_count, "goutteurs"),
            "sector_count": Quantity(data.sector_count, "secteurs"),
            "installation_waste_rate": Quantity(waste, "ratio"),
        },
        outputs={
            "line_count": Quantity(len(lines), "lignes"),
            "dripline_length_m": Quantity(q(dripline_m, 2), "m"),
        },
        formula="quantité = quantité théorique × (1 + taux de perte) ; arrondi supérieur "
        "au conditionnement",
        assumptions=[
            "Les accessoires non listés (colliers, coudes, manchons) sont à ajouter manuellement."
        ],
    )
    return result, lines
