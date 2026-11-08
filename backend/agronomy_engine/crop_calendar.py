"""Crop calendar generation (AGRONOMY_ENGINE.md §7, FR-033, FR-060).

Phases are chained from a start date with their durations; program items
(fertilization, treatments...) are positioned relative to a phase or to the
start date. The engine only *proposes* tasks: they are created in the database
from a validated plan version only.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.result import CalculationResult, Quantity

# Phases that are field operations (and become tasks); the others are crop stages.
OPERATIONAL_PHASES = frozenset(
    {"soil_preparation", "sowing", "nursery", "transplanting", "harvest"}
)


@dataclass(frozen=True)
class PhaseSpec:
    code: str
    duration_days: int | None


@dataclass(frozen=True)
class ProgramItem:
    ref: str  # stable reference of the source plan item
    task_type: str
    title: str
    phase_code: str | None = None
    offset_days: int = 0
    duration_days: int = 1


@dataclass(frozen=True)
class CalendarInput:
    start_date: date | None
    phases: list[PhaseSpec]
    program: list[ProgramItem] = field(default_factory=list)


@dataclass(frozen=True)
class DatedPhase:
    code: str
    sequence: int
    start_date: date
    end_date: date
    duration_days: int


@dataclass(frozen=True)
class TaskProposal:
    source_ref: str
    task_type: str
    title: str
    planned_start_date: date
    planned_end_date: date
    phase_code: str | None


def compute_calendar(
    data: CalendarInput,
) -> tuple[CalculationResult, list[DatedPhase], list[TaskProposal]]:
    if data.start_date is None:
        raise MissingInputError(["start_date"])
    if not data.phases:
        raise MissingInputError(["phases"])
    missing = [f"phase.{p.code}.duration_days" for p in data.phases if p.duration_days is None]
    if missing:
        raise MissingInputError(missing)
    codes = [p.code for p in data.phases]
    if len(codes) != len(set(codes)):
        raise InvalidInputError("phases", "code de phase dupliqué")

    dated: list[DatedPhase] = []
    cursor = data.start_date
    for index, phase in enumerate(data.phases, start=1):
        duration = phase.duration_days
        if duration is None or duration < 1:
            raise InvalidInputError(f"phase.{phase.code}.duration_days", "au moins 1 jour")
        end = cursor + timedelta(days=duration - 1)
        dated.append(DatedPhase(phase.code, index, cursor, end, duration))
        cursor = end + timedelta(days=1)
    cycle_end = dated[-1].end_date
    by_code = {p.code: p for p in dated}

    warnings: list[str] = []
    proposals: list[TaskProposal] = []
    for dated_phase in dated:
        if dated_phase.code in OPERATIONAL_PHASES:
            proposals.append(
                TaskProposal(
                    source_ref=f"phase:{dated_phase.code}",
                    task_type=dated_phase.code,
                    title=f"Phase : {dated_phase.code}",
                    planned_start_date=dated_phase.start_date,
                    planned_end_date=dated_phase.end_date,
                    phase_code=dated_phase.code,
                )
            )
    for item in data.program:
        if item.duration_days < 1:
            raise InvalidInputError(f"program.{item.ref}.duration_days", "au moins 1 jour")
        if item.phase_code is not None:
            anchor = by_code.get(item.phase_code)
            if anchor is None:
                raise InvalidInputError(
                    f"program.{item.ref}.phase_code", "phase absente du calendrier"
                )
            start = anchor.start_date + timedelta(days=item.offset_days)
        else:
            start = data.start_date + timedelta(days=item.offset_days)
        end = start + timedelta(days=item.duration_days - 1)
        if start < data.start_date or end > cycle_end:
            warnings.append(f"L'intervention « {item.title} » sort de la période du cycle.")
        proposals.append(
            TaskProposal(item.ref, item.task_type, item.title, start, end, item.phase_code)
        )
    proposals.sort(key=lambda p: (p.planned_start_date, p.source_ref))

    result = CalculationResult(
        calc_type="calendar.phases",
        inputs={
            "start_date": Quantity(data.start_date.isoformat(), "date"),
            **{
                f"phase.{p.code}.duration_days": Quantity(p.duration_days, "days")
                for p in data.phases
            },
        },
        outputs={
            "cycle_start_date": Quantity(data.start_date.isoformat(), "date"),
            "cycle_end_date": Quantity(cycle_end.isoformat(), "date"),
            "cycle_duration_days": Quantity((cycle_end - data.start_date).days + 1, "days"),
            "task_proposal_count": Quantity(len(proposals), "tâches"),
        },
        formula="début(i) = fin(i−1) + 1 j ; fin(i) = début(i) + durée(i) − 1 j",
        assumptions=["Les phases s'enchaînent sans chevauchement ni interruption."],
        warnings=warnings,
        details={
            "phases": [
                {
                    "code": p.code,
                    "sequence": p.sequence,
                    "start_date": p.start_date.isoformat(),
                    "end_date": p.end_date.isoformat(),
                    "duration_days": p.duration_days,
                }
                for p in dated
            ],
        },
    )
    return result, dated, proposals
