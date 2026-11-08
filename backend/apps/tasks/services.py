"""Task services (FR-060..064, FR-082).

- Tasks are generated only from a VALIDATED plan version (FR-035, FR-060).
- Regeneration (FR-064) never rewrites the history: started, done or
  to-verify tasks are kept; only untouched future tasks are re-planned, and
  a re-planned task is cancelled and linked to its replacement.
- Reports are append-only; a report on a cancelled task is kept and the task is
  flagged "à vérifier" (OFFLINE_SYNC.md §6.2).
"""

import uuid
import zoneinfo
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from agronomy_engine.crop_calendar import CalendarInput, PhaseSpec, ProgramItem, compute_calendar
from agronomy_engine.errors import EngineError
from apps.agronomy.models import InputProduct, PlannedFertilization, PlannedPhytoIntervention
from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, IdentifierConflictError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.farms.models import Farm, FarmMembership
from apps.files.models import StoredFile
from apps.files.services import require_usable_file
from apps.production_plans.models import CropCycle, PlanVersion
from apps.synchronization.registry import SyncConflictRaised
from apps.synchronization.services import flag_conflict, record_change
from apps.tasks.models import InputConsumption, Task, TaskReport, TaskStatusEvent, Team

VIEW, EDIT, ASSIGN, REPORT = "tasks.view", "tasks.edit", "tasks.assign", "tasks.report"
TASK_ENTITY = "tasks.task"
REPORT_ENTITY = "tasks.task_report"
S = Task.Status

TRANSITIONS: dict[str, set[str]] = {
    S.TODO: {S.IN_PROGRESS, S.DONE, S.CANCELLED},
    S.IN_PROGRESS: {S.TODO, S.DONE, S.CANCELLED, S.TO_VERIFY},
    S.DONE: {S.TO_VERIFY},
    S.TO_VERIFY: {S.DONE, S.IN_PROGRESS, S.CANCELLED},
    S.CANCELLED: {S.TODO},
}
# Transitions a field worker may perform with `tasks.report`; the others need `tasks.edit`.
WORKER_TRANSITIONS = {
    (S.TODO, S.IN_PROGRESS),
    (S.IN_PROGRESS, S.DONE),
    (S.TODO, S.DONE),
    (S.IN_PROGRESS, S.TODO),
}
KEPT_STATUSES = {S.IN_PROGRESS, S.DONE, S.TO_VERIFY}
MASS_TO_KG = {"kg": Decimal(1), "g": Decimal("0.001")}
VOLUME_TO_L = {"l": Decimal(1), "ml": Decimal("0.001")}


def farm_today(farm_id: uuid.UUID) -> date:
    tz = zoneinfo.ZoneInfo(Farm.objects.only("timezone").get(id=farm_id).timezone)
    return timezone.now().astimezone(tz).date()


def is_late(task: Task, today: date) -> bool:
    """Derived status "En retard" (FR-062)."""
    return task.status in {S.TODO, S.IN_PROGRESS} and task.planned_end_date < today


def _change(ctx: TenantContext, task: Task, origin_op_id: uuid.UUID | None = None) -> None:
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=TASK_ENTITY,
        entity_id=task.id,
        entity_version=task.version,
        required_permission=VIEW,
        origin_op_id=origin_op_id,
    )


def _set_status(
    ctx: TenantContext,
    task: Task,
    to_status: str,
    reason: str = "",
    origin_op_id: uuid.UUID | None = None,
) -> None:
    TaskStatusEvent.objects.create(
        task=task,
        from_status=task.status,
        to_status=to_status,
        actor=ctx.user,
        reason=reason,
        origin_op_id=origin_op_id,
    )
    task.status = to_status
    task.version += 1
    task.updated_by = ctx.user
    task.save()
    _change(ctx, task, origin_op_id)


def _locked_task(ctx: TenantContext, task_id: Any) -> Task:
    task = Task.objects.select_for_update().filter(id=task_id, farm_id=ctx.require_farm_id).first()
    if task is None:
        raise NotFoundError()
    return task


# --- Generation ----------------------------------------------------------------------


def _proposals(version: PlanVersion) -> list[Any]:
    phases = list(version.phases.all())
    program: list[ProgramItem] = []
    for item in PlannedFertilization.objects.filter(plan_version=version).select_related("product"):
        program.append(
            ProgramItem(
                ref=f"fertilization:{item.sequence}",
                task_type="fertilization",
                title=f"Fertilisation : {item.product.name}",
                phase_code=item.phase_code or None,
                offset_days=item.day_offset,
            )
        )
    for phyto in PlannedPhytoIntervention.objects.filter(plan_version=version).select_related(
        "product"
    ):
        program.append(
            ProgramItem(
                ref=f"phyto:{phyto.sequence}",
                task_type="phyto",
                title=f"Traitement : {phyto.product.name} ({phyto.target_organism})",
                phase_code=phyto.phase_code or None,
                offset_days=phyto.day_offset,
            )
        )
    try:
        _, _, proposals = compute_calendar(
            CalendarInput(
                start_date=version.planned_start_date,
                phases=[PhaseSpec(p.phase_code, p.duration_days) for p in phases],
                program=program,
            )
        )
    except EngineError as exc:
        raise BusinessRuleError(f"Calendrier incomplet : {exc}") from exc
    return proposals


@transaction.atomic
def generate_tasks(ctx: TenantContext, *, version_id: uuid.UUID) -> dict[str, int]:
    ctx.require(EDIT)
    version = PlanVersion.objects.filter(id=version_id, farm_id=ctx.require_farm_id).first()
    if version is None:
        raise NotFoundError()
    if version.status != PlanVersion.Status.VALIDATED:
        raise BusinessRuleError(
            "Les tâches ne sont générées qu'à partir d'une version validée du plan."
        )
    cycles = list(
        CropCycle.objects.filter(plan_version=version)
        .exclude(status=CropCycle.Status.CANCELLED)
        .select_related("parcel")
    )
    if not cycles:
        raise BusinessRuleError("Aucun cycle cultural actif pour cette version.")
    proposals = _proposals(version)
    batch = uuid.uuid4()
    existing = {
        (t.source_ref, t.parcel_id): t
        for t in Task.objects.select_for_update()
        .filter(farm_id=ctx.require_farm_id, plan_id=version.plan_id, origin=Task.Origin.GENERATED)
        .exclude(status=S.CANCELLED)
    }
    summary = {"created": 0, "unchanged": 0, "replanned": 0, "cancelled": 0, "kept": 0}
    for cycle in cycles:
        for proposal in proposals:
            key = (proposal.source_ref, cycle.parcel_id)
            current = existing.pop(key, None)
            fields = {
                "task_type": proposal.task_type,
                "title": proposal.title,
                "planned_start_date": proposal.planned_start_date,
                "planned_end_date": proposal.planned_end_date,
            }
            if current is not None and current.status in KEPT_STATUSES:
                summary["kept"] += 1  # history of started/done work is never rewritten
                continue
            if current is not None and all(getattr(current, k) == v for k, v in fields.items()):
                current.plan_version = version
                current.version += 1
                current.save()
                _change(ctx, current)
                summary["unchanged"] += 1
                continue
            task = Task.objects.create(
                organization_id=ctx.organization_id,
                farm_id=ctx.require_farm_id,
                plan_version=version,
                plan_id=version.plan_id,
                crop_cycle=cycle,
                parcel=cycle.parcel,
                origin=Task.Origin.GENERATED,
                source_ref=proposal.source_ref,
                generation_batch=batch,
                created_by=ctx.user,
                updated_by=ctx.user,
                **fields,
            )
            _change(ctx, task)
            if current is None:
                summary["created"] += 1
            else:
                current.superseded_by = task
                _set_status(ctx, current, S.CANCELLED, "Replanifiée (nouvelle version du plan)")
                summary["replanned"] += 1
    for leftover in existing.values():
        if leftover.status == S.TODO:
            _set_status(ctx, leftover, S.CANCELLED, "Retirée du plan")
            summary["cancelled"] += 1
        else:
            summary["kept"] += 1
    record_event(
        action="tasks.generated",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        entity_type="production_plans.plan_version",
        entity_id=version.id,
        after={"batch": str(batch), **summary},
    )
    return summary


# --- Manual tasks, assignment, status --------------------------------------------------


def _check_task_links(ctx: TenantContext, data: dict[str, Any]) -> None:
    parcel = data.get("parcel")
    if parcel is not None and (parcel.farm_id != ctx.farm_id or parcel.deleted_at is not None):
        raise BusinessRuleError("Parcelle introuvable.", field_errors={"parcel": ["Introuvable."]})
    start, end = data.get("planned_start_date"), data.get("planned_end_date")
    if start and end and end < start:
        raise BusinessRuleError(
            "Dates incohérentes.", field_errors={"planned_end_date": ["Avant le début."]}
        )


@transaction.atomic
def create_task(ctx: TenantContext, *, data: dict[str, Any]) -> Task:
    ctx.require(EDIT)
    _check_task_links(ctx, data)
    task = Task.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        origin=Task.Origin.MANUAL,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    _change(ctx, task)
    return task


@transaction.atomic
def update_task(
    ctx: TenantContext, *, task_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> Task:
    from apps.core.versioning import apply_changes, check_version

    ctx.require(EDIT)
    task = _locked_task(ctx, task_id)
    check_version(task, expected_version)
    if task.status not in {S.TODO, S.IN_PROGRESS}:
        raise BusinessRuleError("Seule une tâche à faire ou en cours est modifiable.")
    merged = {
        "planned_start_date": task.planned_start_date,
        "planned_end_date": task.planned_end_date,
        **changes,
    }
    _check_task_links(ctx, merged)
    if apply_changes(task, changes):
        task.version += 1
        task.updated_by = ctx.user
        task.save()
        _change(ctx, task)
    return task


@transaction.atomic
def assign_task(
    ctx: TenantContext, *, task_id: uuid.UUID, user_ids: list[uuid.UUID], team_ids: list[uuid.UUID]
) -> Task:
    ctx.require(ASSIGN)
    task = _locked_task(ctx, task_id)
    members = set(
        FarmMembership.objects.filter(
            farm_id=ctx.require_farm_id, status="active", user_id__in=user_ids
        ).values_list("user_id", flat=True)
    )
    unknown = [str(u) for u in user_ids if u not in members]
    if unknown:
        raise BusinessRuleError(
            "Utilisateurs hors de l'exploitation.", field_errors={"users": unknown}
        )
    teams = list(Team.objects.filter(farm_id=ctx.require_farm_id, id__in=team_ids))
    if len(teams) != len(set(team_ids)):
        raise BusinessRuleError("Équipe introuvable.", field_errors={"teams": ["Introuvable."]})
    task.assignees.set(list[Any](user_ids))
    task.teams.set(teams)
    task.version += 1
    task.save()
    _change(ctx, task)
    return task


@transaction.atomic
def change_status(
    ctx: TenantContext,
    *,
    task_id: Any,
    to_status: str,
    expected_from: str | None = None,
    reason: str = "",
    origin_op_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    task = _locked_task(ctx, task_id)
    if expected_from is not None and expected_from != task.status:
        if task.status == to_status:
            return {"entity_version": task.version, "converged": True}
        # Offline transition based on a stale status (OFFLINE_SYNC.md §6.2).
        raise SyncConflictRaised(
            "invalid_transition",
            fields=["status"],
            server={"status": task.status, "version": task.version},
            message=f"La tâche est « {task.get_status_display()} » sur le serveur.",
        )
    if to_status not in TRANSITIONS.get(task.status, set()):
        raise BusinessRuleError(f"Transition impossible : {task.status} → {to_status}.")
    ctx.require(REPORT if (task.status, to_status) in WORKER_TRANSITIONS else EDIT)
    _set_status(ctx, task, to_status, reason, origin_op_id)
    return {"entity_version": task.version}


def sync_change_status(
    ctx: TenantContext,
    *,
    entity_id: uuid.UUID,
    payload: dict[str, Any],
    base_version: int | None,
    origin_op_id: uuid.UUID,
) -> dict[str, Any]:
    """Sync command `task.change_status`: payload {"from": ..., "to": ..., "reason": ...}."""
    if "to" not in payload or "from" not in payload:
        raise BusinessRuleError("Statuts « from » et « to » obligatoires.")
    return change_status(
        ctx,
        task_id=entity_id,
        to_status=payload["to"],
        expected_from=payload["from"],
        reason=payload.get("reason", ""),
        origin_op_id=origin_op_id,
    )


# --- Reports -------------------------------------------------------------------------


def _base_quantity(quantity: Decimal, unit: str) -> tuple[Decimal, str]:
    if unit in MASS_TO_KG:
        return quantity * MASS_TO_KG[unit], "kg"
    if unit in VOLUME_TO_L:
        return quantity * VOLUME_TO_L[unit], "l"
    raise BusinessRuleError(
        "Unité de consommation inconnue (kg, g, l, ml).", field_errors={"unit": [unit]}
    )


@transaction.atomic
def create_report(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[TaskReport, bool]:
    ctx.require(REPORT)
    data = dict(data)
    consumptions = data.pop("consumptions", [])
    photos = data.pop("photos", [])
    report_id = data.get("id")
    if report_id is not None:
        existing = TaskReport.objects.filter(id=report_id).first()
        if existing is not None:
            if existing.farm_id != ctx.farm_id:
                raise IdentifierConflictError("Identifiant déjà utilisé.")
            return existing, False
    task = _locked_task(ctx, data["task"].id)
    start, end = data["actual_start"], data.get("actual_end")
    if end is not None and end < start:
        raise BusinessRuleError("Fin avant le début.", field_errors={"actual_end": ["Invalide."]})
    if data.get("duration_minutes") is None and end is not None:
        data["duration_minutes"] = int((end - start).total_seconds() // 60)
    report = TaskReport.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        reported_by=ctx.user,
        **{**data, "task": task},
    )
    for photo in photos:
        report.photos.add(require_usable_file(ctx, photo.id, StoredFile.Purpose.TASK_PHOTO))
    for index, line in enumerate(consumptions):
        product: InputProduct = line["product"]
        if product.organization_id != ctx.organization_id:
            raise BusinessRuleError(
                "Produit introuvable.",
                field_errors={f"consumptions.{index}.product": ["Introuvable."]},
            )
        if line["quantity"] <= 0:
            raise BusinessRuleError(
                "Quantité invalide.", field_errors={f"consumptions.{index}.quantity": ["> 0"]}
            )
        base, base_unit = _base_quantity(line["quantity"], line["unit"])
        InputConsumption.objects.create(
            report=report,
            product=product,
            quantity=line["quantity"],
            unit=line["unit"],
            quantity_base=base,
            base_unit=base_unit,
            plan_version=task.plan_version,
            lot_number=line.get("lot_number", ""),
        )

    complete = report.completion == TaskReport.Completion.COMPLETE
    if task.status == S.CANCELLED:
        # The work was done in the field: keep the report, ask a supervisor to check.
        _set_status(ctx, task, S.TO_VERIFY, "Compte rendu reçu sur une tâche annulée", origin_op_id)
        flag_conflict(
            ctx,
            entity_type=TASK_ENTITY,
            entity_id=task.id,
            conflict_type="invalid_transition",
            message="Compte rendu sur une tâche annulée : à vérifier.",
            client_payload={"report": str(report.id)},
            server_snapshot={"status": S.CANCELLED},
        )
    elif complete and task.status in {S.TODO, S.IN_PROGRESS}:
        _set_status(ctx, task, S.DONE, "Compte rendu de fin d'intervention", origin_op_id)
    elif not complete and task.status == S.TODO:
        _set_status(ctx, task, S.IN_PROGRESS, "Compte rendu partiel", origin_op_id)
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=REPORT_ENTITY,
        entity_id=report.id,
        entity_version=1,
        required_permission=VIEW,
        origin_op_id=origin_op_id,
    )
    return report, True


@transaction.atomic
def create_team(ctx: TenantContext, *, name: str, member_ids: list[uuid.UUID]) -> Team:
    ctx.require(ASSIGN)
    members = set(
        FarmMembership.objects.filter(
            farm_id=ctx.require_farm_id, status="active", user_id__in=member_ids
        ).values_list("user_id", flat=True)
    )
    if members != set(member_ids):
        raise BusinessRuleError(
            "Membres hors de l'exploitation.", field_errors={"members": ["Invalide."]}
        )
    team = Team.objects.create(
        organization_id=ctx.organization_id, farm_id=ctx.require_farm_id, name=name
    )
    team.members.set(list[Any](member_ids))
    return team
