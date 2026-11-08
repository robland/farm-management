"""AI assistant services (ARCHITECTURE.md §8, CLAUDE.md §10, FR-100..107).

Pipeline guarantees:
- Outputs are validated against versioned JSON schemas; non-conforming output is rejected.
- A value is classified "document" only if its quote is found verbatim (normalised
  whitespace and case) on the cited page of the extracted PDF text; otherwise it is
  an AI suggestion. Assumptions are never presented as documentation.
- The AI writes drafts only: technical data sets stay `draft`, plans stay `draft`,
  every AI suggestion must be decided by a human before the plan can be validated.
- No fertilizer or phytosanitary dose is ever taken from the AI.
- Without a provider the run is recorded as `unavailable` and manual creation remains possible.
"""

import io
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import jsonschema
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai_assistant import prompts, schemas
from apps.ai_assistant.models import AIRequestLog, AIRun, AISuggestion
from apps.ai_assistant.providers import (
    DocumentPart,
    LLMRequest,
    LLMUsage,
    ProviderError,
    ProviderUnavailableError,
    get_provider,
)
from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, DomainError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.farms.models import Farm
from apps.files.services import open_file
from apps.production_plans import services as plans
from apps.production_plans.models import FieldProvenance, PlanPhase, PlantingSpec, PlanVersion
from apps.varieties import services as varieties
from apps.varieties.models import TechnicalDataItem, TechnicalDocument, Variety
from apps.varieties.technical_keys import PHASE_CODE_PATTERN, PHASE_CODES, TECHNICAL_KEYS

AI_USE = "ai.use"
SK = FieldProvenance.SourceKind
INTEGER_FIELDS = {"plants_per_hole", "seeds_per_hole", "rows_per_bed"}
CHOICE_FIELDS = {
    "planting_method": PlantingSpec.Method.values,
    "layout": PlantingSpec.Layout.values,
}


class AIUnavailableError(DomainError):
    code = "ai_unavailable"
    http_status = 503


class AIProviderFailedError(DomainError):
    code = "ai_provider_error"
    http_status = 502


class QuotaExceededError(DomainError):
    code = "ai_quota_exceeded"
    http_status = 429


# --- Provider calls -----------------------------------------------------------------------


def _check_quota(ctx: TenantContext) -> None:
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = AIRequestLog.objects.filter(
        organization_id=ctx.organization_id, created_at__gte=month_start
    ).count()
    if used >= settings.FMS_AI_MONTHLY_REQUEST_LIMIT:
        raise QuotaExceededError(
            "Quota mensuel d'appels IA atteint pour l'organisation.",
            details={"limit": settings.FMS_AI_MONTHLY_REQUEST_LIMIT},
        )


def _estimated_cost(usage: LLMUsage) -> Decimal | None:
    prices = settings.FMS_AI_PRICES_USD_PER_MTOK.get(usage.model)
    if prices is None:
        return None
    return (
        Decimal(usage.input_tokens) * Decimal(prices["input"])
        + Decimal(usage.output_tokens) * Decimal(prices["output"])
    ) / Decimal(1_000_000)


def _log(
    run: AIRun, provider_name: str, usage: LLMUsage | None, status: str, error_code: str = ""
) -> None:
    usage = usage or LLMUsage()
    AIRequestLog.objects.create(
        organization_id=run.organization_id,
        run=run,
        provider=provider_name,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost=_estimated_cost(usage),
        latency_ms=usage.latency_ms,
        status=status,
        error_code=error_code,
        request_id=usage.request_id,
    )


def _fail(run: AIRun, status: str, code: str, message: str) -> None:
    run.status = status
    run.error_code = code
    run.error_message = message
    run.finished_at = timezone.now()
    run.save()


def _call(ctx: TenantContext, run: AIRun, request: LLMRequest) -> dict[str, Any]:
    """Call the provider, log tokens/cost/errors, validate the output schema."""
    try:
        provider = get_provider()
        run.provider, run.model = provider.name, provider.model
        run.save(update_fields=["provider", "model"])
        response = provider.generate_json(request)
    except ProviderUnavailableError as exc:
        _fail(run, AIRun.Status.UNAVAILABLE, "unavailable", str(exc))
        raise AIUnavailableError(
            "Assistant IA indisponible : la saisie manuelle reste possible.",
            details={"run": str(run.id)},
        ) from exc
    except ProviderError as exc:
        _log(run, run.provider, exc.usage, "error", exc.code)
        _fail(run, AIRun.Status.FAILED, exc.code, exc.message)
        raise AIProviderFailedError(
            exc.message, details={"run": str(run.id), "code": exc.code, "retryable": exc.retryable}
        ) from exc
    try:
        jsonschema.validate(response.data, request.schema)
    except jsonschema.ValidationError as exc:
        _log(run, run.provider, response.usage, "invalid_output", "schema_mismatch")
        _fail(run, AIRun.Status.FAILED, "schema_mismatch", exc.message)
        raise AIProviderFailedError(
            "Réponse IA non conforme au schéma attendu.", details={"run": str(run.id)}
        ) from exc
    _log(run, run.provider, response.usage, "ok")
    run.raw_output = response.data
    return response.data


# --- Extraction (FR-100, FR-101) -----------------------------------------------------------


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return [_normalize(page.extract_text() or "") for page in reader.pages]
    except Exception:  # unreadable or scanned PDF: citations cannot be verified
        return []


def quote_is_verified(pages: list[str], page: int | None, quote: str) -> bool:
    if not page or not quote.strip() or page < 1 or page > len(pages):
        return False
    return _normalize(quote) in pages[page - 1]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"nombre invalide : {value}") from exc


def _catalogue_text() -> str:
    lines = [
        f"- {key} ({spec.unit or 'texte'}) : {spec.label}" for key, spec in TECHNICAL_KEYS.items()
    ]
    lines.append(
        "- phase.<code>.duration_days (days) : durée d'une phase, codes : " + ", ".join(PHASE_CODES)
    )
    lines.append("- kc.<code> (ratio) : coefficient cultural d'une phase")
    return "\n".join(lines)


def run_extraction(ctx: TenantContext, *, document_id: uuid.UUID) -> AIRun:
    """Extract technical data from a technical sheet into a DRAFT data set."""
    ctx.require(AI_USE)
    ctx.require(varieties.EDIT)
    document = (
        TechnicalDocument.objects.select_related("file", "variety")
        .filter(id=document_id, organization_id=ctx.organization_id)
        .first()
    )
    if document is None:
        raise NotFoundError()
    _check_quota(ctx)
    with open_file(document.file) as handle:
        data = handle.read()
    is_pdf = document.file.detected_mime == "application/pdf"
    pages = pdf_pages(data) if is_pdf else []
    run = AIRun.objects.create(
        organization_id=ctx.organization_id,
        kind=AIRun.Kind.EXTRACTION,
        document=document,
        provider="",
        prompt_version=prompts.PROMPT_VERSION,
        schema_version=schemas.EXTRACTION_SCHEMA_VERSION,
        requested_by=ctx.user,
        input_snapshot={"document": str(document.id), "pages": len(pages)},
    )
    output = _call(
        ctx,
        run,
        LLMRequest(
            system=prompts.EXTRACTION_SYSTEM,
            text=(
                f"Variété : {document.variety.name}\nCatalogue des clés et unités :\n"
                f"{_catalogue_text()}\n\nExtrais les données de la fiche jointe."
            ),
            schema=schemas.EXTRACTION_SCHEMA,
            documents=[DocumentPart(document.file.detected_mime, data)],
        ),
    )
    with transaction.atomic():
        data_set = varieties.create_data_set(
            ctx,
            variety_id=document.variety_id,
            source_document_id=document.id,
            notes="Brouillon issu d'une extraction IA",
        )
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in output["items"]:
            key = raw["key"]
            if key in seen:
                rejected.append({"item": raw, "errors": ["Clé en double."]})
                continue
            verified = quote_is_verified(pages, raw["page"], raw["quote"])
            try:
                item = {
                    "key": key,
                    "value_numeric": _decimal(raw["value"]),
                    "value_min": _decimal(raw["value_min"]),
                    "value_max": _decimal(raw["value_max"]),
                    "value_text": raw["value_text"] or "",
                    "unit": raw["unit"],
                    "provenance": (
                        TechnicalDataItem.Provenance.DOCUMENT
                        if verified
                        else TechnicalDataItem.Provenance.AI_EXTRACTION
                    ),
                    "source_page": raw["page"],
                    "source_quote": raw["quote"],
                    "confidence": _decimal(raw["confidence"]),
                    "notes": ""
                    if verified
                    else "Citation non retrouvée dans le texte du document : à vérifier.",
                }
                if item["confidence"] is not None and not 0 <= item["confidence"] <= 1:
                    item["confidence"] = None
                accepted.append(varieties.validate_item(data_set, item))
                seen.add(key)
            except (BusinessRuleError, ValueError) as exc:
                errors = getattr(exc, "field_errors", None) or {key: [str(exc)]}
                rejected.append({"item": raw, "errors": errors})
        if accepted:
            varieties.upsert_items(ctx, data_set_id=data_set.id, items=accepted)
        document.status = TechnicalDocument.Status.EXTRACTED
        document.save(update_fields=["status"])
        run.data_set = data_set
        run.rejected_items = rejected
        run.missing_info = [
            {"field": m, "question": "Absent de la fiche"} for m in output["missing"]
        ]
        run.status = AIRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save()
        record_event(
            action="ai.extraction.completed",
            actor=ctx.user,
            organization_id=ctx.organization_id,
            entity_type="ai_assistant.run",
            entity_id=run.id,
            after={"accepted": len(accepted), "rejected": len(rejected)},
        )
    return run


# --- Plan draft (FR-031, FR-102..105) --------------------------------------------------------


def _parse_planting(field: str, value: str | None) -> Any:
    if value is None:
        return None
    if field in CHOICE_FIELDS:
        if value not in CHOICE_FIELDS[field]:
            raise ValueError(f"valeur inconnue : {value}")
        return value
    number = _decimal(value)
    if number is None:
        return None
    if field in INTEGER_FIELDS:
        if number != number.to_integral_value() or number < 1:
            raise ValueError("entier positif attendu")
        return int(number)
    if number <= 0:
        raise ValueError("valeur positive attendue")
    if field.endswith("_rate") and number > 1:
        raise ValueError("fraction entre 0 et 1 attendue")
    return number


def _context_text(
    variety: Variety, items: dict[str, TechnicalDataItem], farm: Farm, data: dict[str, Any]
) -> str:
    parcel = data["parcel"]
    context = {
        "variete": {
            "nom": variety.name,
            "culture": variety.crop.common_name,
            "semencier": variety.seed_company,
        },
        "donnees_techniques_validees": [
            {
                "technical_key": key,
                "value": str(i.value_numeric) if i.value_numeric is not None else None,
                "min": str(i.value_min) if i.value_min is not None else None,
                "max": str(i.value_max) if i.value_max is not None else None,
                "text": i.value_text,
                "unit": i.unit,
            }
            for key, i in sorted(items.items())
        ],
        "parcelle": {
            "surface_allouee_m2": str(data["allocated_area_m2"]),
            "type_sol": parcel.soil_type,
            "ph": str(parcel.soil_ph or ""),
            "disponibilite_eau": parcel.water_availability,
        },
        "exploitation": {"pays": farm.country, "region": farm.region, "localite": farm.locality},
        "date_debut_souhaitee": data["planned_start_date"].isoformat(),
        "objectifs": data.get("objectives", ""),
        "contraintes": data.get("constraints", ""),
        "codes_de_phase": PHASE_CODES,
        "champs_de_plantation": plans.PLANTING_FIELDS,
    }
    return (
        "Contexte (JSON) :\n"
        + json.dumps(context, ensure_ascii=False, indent=1)
        + "\n\nPropose un brouillon (paramètres de plantation et phases)."
    )


def _document_backed(
    items: dict[str, TechnicalDataItem], key: str | None, value: Any
) -> TechnicalDataItem | None:
    """The suggestion is "document" only if it repeats a validated value exactly."""
    item = items.get(key or "")
    if item is None or item.value_numeric is None or value is None:
        return None
    try:
        return item if Decimal(str(value)) == item.value_numeric else None
    except InvalidOperation:
        return None


def run_plan_draft(ctx: TenantContext, *, data: dict[str, Any]) -> AIRun:
    ctx.require(AI_USE)
    ctx.require(plans.EDIT)
    variety: Variety = data["variety"]
    if variety.organization_id != ctx.organization_id:
        raise BusinessRuleError("Variété introuvable.", field_errors={"variety": ["Introuvable."]})
    _check_quota(ctx)
    items = varieties.validated_values(variety)
    farm = Farm.objects.get(id=ctx.require_farm_id)
    run = AIRun.objects.create(
        organization_id=ctx.organization_id,
        farm=farm,
        kind=AIRun.Kind.PLAN_DRAFT,
        provider="",
        prompt_version=prompts.PROMPT_VERSION,
        schema_version=schemas.PLAN_DRAFT_SCHEMA_VERSION,
        requested_by=ctx.user,
        input_snapshot={k: str(getattr(v, "pk", v)) for k, v in data.items()},
    )
    output = _call(
        ctx,
        run,
        LLMRequest(
            system=prompts.PLAN_DRAFT_SYSTEM,
            text=_context_text(variety, items, farm, data),
            schema=schemas.PLAN_DRAFT_SCHEMA,
        ),
    )
    try:
        return _apply_plan_draft(ctx, run, output, variety, items, data)
    except DomainError as exc:
        _fail(run, AIRun.Status.FAILED, exc.code, exc.message)
        raise


def _apply_plan_draft(
    ctx: TenantContext,
    run: AIRun,
    output: dict[str, Any],
    variety: Variety,
    items: dict[str, TechnicalDataItem],
    data: dict[str, Any],
) -> AIRun:
    missing: list[dict[str, Any]] = list(output["missing_info"])
    if not items:
        missing.append(
            {
                "field": "technical_data",
                "question": "Aucune donnée technique validée pour cette variété.",
            }
        )
    rejected: list[dict[str, Any]] = []
    with transaction.atomic():
        plan = plans.create_plan(
            ctx,
            campaign_id=data["campaign"].id,
            variety_id=variety.id,
            name=data.get("name") or f"Brouillon IA — {variety.name}",
            origin=PlanVersion.Origin.AI_DRAFT,
        )
        version = plan.versions.get()

        def current() -> int:
            return PlanVersion.objects.get(id=version.id).version

        plans.set_allocations(
            ctx,
            version_id=version.id,
            expected_version=current(),
            allocations=[
                {
                    "parcel": data["parcel"],
                    "allocated_area_m2": data["allocated_area_m2"],
                    "non_plantable_area_m2": data.get("non_plantable_area_m2"),
                }
            ],
        )
        plans.update_header(
            ctx,
            version_id=version.id,
            expected_version=current(),
            changes={
                "planned_start_date": data["planned_start_date"],
                "objectives": data.get("objectives", ""),
                "constraints_notes": data.get("constraints", ""),
                "technical_data_set": next(iter(items.values())).data_set if items else None,
            },
        )

        changes: dict[str, Any] = {}
        documented: dict[str, TechnicalDataItem] = {}
        suggestions: dict[str, AISuggestion] = {}
        for entry in output["planting"]:
            field = entry["field"]
            try:
                value = _parse_planting(field, entry["value"])
            except ValueError as exc:
                rejected.append({"item": entry, "errors": [str(exc)]})
                continue
            if value is None:
                missing.append({"field": f"planting_spec.{field}", "question": entry["rationale"]})
                continue
            changes[field] = value
            item = (
                _document_backed(items, entry["technical_key"], value)
                if entry["source"] == "document"
                else None
            )
            if item is not None:
                documented[field] = item
            else:
                suggestions[field] = AISuggestion.objects.create(
                    run=run,
                    plan_version=version,
                    field_path=f"planting_spec.{field}",
                    value=str(value),
                    rationale=entry["rationale"],
                )
        if changes:
            plans.update_planting_spec(
                ctx,
                version_id=version.id,
                expected_version=current(),
                changes=changes,
                source_kind=SK.AI_SUGGESTION,
                ai_suggestion_ids={f: s.id for f, s in suggestions.items()},
            )
            for field, item in documented.items():
                plans.set_provenance(
                    version,
                    f"planting_spec.{field}",
                    SK.DOCUMENT,
                    user=ctx.user,
                    item=item,
                    note="Reprise par l'IA d'une donnée validée",
                )

        phases: list[dict[str, Any]] = []
        for entry in output["phases"]:
            code, duration = entry["phase_code"], entry["duration_days"]
            if not PHASE_CODE_PATTERN.match(code) or any(p["phase_code"] == code for p in phases):
                rejected.append({"item": entry, "errors": ["Code de phase invalide ou en double."]})
                continue
            if duration is not None and duration < 1:
                rejected.append({"item": entry, "errors": ["Durée invalide."]})
                continue
            phases.append({"phase_code": code, "duration_days": duration, "entry": entry})
        if phases:
            plans.set_phases(
                ctx,
                version_id=version.id,
                expected_version=current(),
                phases=[{k: p[k] for k in ("phase_code", "duration_days")} for p in phases],
                source_kind=SK.AI_SUGGESTION,
            )
            for phase in phases:
                entry, path = phase["entry"], f"phases.{phase['phase_code']}.duration_days"
                if phase["duration_days"] is None:
                    missing.append({"field": path, "question": entry["rationale"]})
                    continue
                item = (
                    _document_backed(items, entry["technical_key"], phase["duration_days"])
                    if entry["source"] == "document"
                    else None
                )
                if item is not None:
                    plans.set_provenance(version, path, SK.DOCUMENT, user=ctx.user, item=item)
                else:
                    suggestion = AISuggestion.objects.create(
                        run=run,
                        plan_version=version,
                        field_path=path,
                        value=phase["duration_days"],
                        rationale=entry["rationale"],
                    )
                    plans.set_provenance(
                        version,
                        path,
                        SK.AI_SUGGESTION,
                        user=ctx.user,
                        ai_suggestion_id=suggestion.id,
                    )
        outcome = plans.compute_version(ctx, version_id=version.id)
        missing += [
            {"field": f"{m['scope']}:{field}", "question": "Donnée manquante pour le calcul"}
            for m in outcome.missing
            for field in m["fields"]
        ]
        run.plan_version = version
        run.missing_info = missing
        run.rejected_items = rejected
        run.status = AIRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save()
        record_event(
            action="ai.plan_draft.completed",
            actor=ctx.user,
            organization_id=ctx.organization_id,
            farm_id=ctx.farm_id,
            entity_type="ai_assistant.run",
            entity_id=run.id,
            after={"plan_version": str(version.id), "suggestions": len(suggestions)},
        )
    return run


@transaction.atomic
def decide_suggestion(
    ctx: TenantContext, *, suggestion_id: uuid.UUID, decision: str, value: Any = None
) -> AISuggestion:
    """Human decision on an AI suggestion (FR-104, FR-105)."""
    ctx.require(plans.EDIT)
    suggestion = (
        AISuggestion.objects.select_for_update()
        .select_related("plan_version")
        .filter(id=suggestion_id, plan_version__farm_id=ctx.require_farm_id)
        .first()
    )
    if suggestion is None:
        raise NotFoundError()
    if suggestion.status != AISuggestion.Status.SUGGESTED:
        raise BusinessRuleError("Suggestion déjà traitée.")
    version = plans.lock_draft_version(ctx, suggestion.plan_version_id, None)
    path = suggestion.field_path
    if decision == "accept":
        suggestion.status = AISuggestion.Status.ACCEPTED
        plans.set_provenance(
            version,
            path,
            SK.AI_SUGGESTION,
            user=ctx.user,
            ai_suggestion_id=suggestion.id,
            note="Recommandation IA acceptée par l'utilisateur",
        )
    elif decision in {"reject", "modify"}:
        if decision == "modify" and value is None:
            raise BusinessRuleError("Valeur obligatoire.", field_errors={"value": ["Obligatoire."]})
        new_value = None
        if decision == "modify":
            try:
                new_value = (
                    _parse_planting(path.split(".", 1)[1], str(value))
                    if path.startswith("planting_spec.")
                    else int(value)
                )
            except (ValueError, TypeError) as exc:
                raise BusinessRuleError(str(exc), field_errors={"value": [str(exc)]}) from exc
        if path.startswith("planting_spec."):
            PlantingSpec.objects.filter(plan_version=version).update(
                **{path.split(".", 1)[1]: new_value}
            )
        else:
            code = path.split(".")[1]
            PlanPhase.objects.filter(plan_version=version, phase_code=code).update(
                duration_days=new_value
            )
        plans.set_provenance(
            version,
            path,
            SK.USER_INPUT,
            user=ctx.user,
            note=f"Suggestion IA {'rejetée' if decision == 'reject' else 'modifiée'}",
        )
        suggestion.status = (
            AISuggestion.Status.REJECTED if decision == "reject" else AISuggestion.Status.MODIFIED
        )
    else:
        raise BusinessRuleError("Décision inconnue (accept, reject, modify).")
    suggestion.decided_by = ctx.user
    suggestion.decided_at = timezone.now()
    suggestion.save()
    plans.touch_version(ctx, version)
    return suggestion


def pending_suggestions_guard(version: PlanVersion) -> list[str]:
    """VALIDATION_GUARDS entry: no validation while AI suggestions are undecided."""
    pending = AISuggestion.objects.filter(
        plan_version=version, status=AISuggestion.Status.SUGGESTED
    ).count()
    return [f"{pending} suggestion(s) IA à accepter, modifier ou rejeter."] if pending else []


def provider_status() -> dict[str, Any]:
    try:
        provider = get_provider()
    except ProviderUnavailableError as exc:
        return {"available": False, "provider": settings.FMS_AI_PROVIDER, "reason": str(exc)}
    return {
        "available": provider.name != "null",
        "provider": provider.name,
        "model": provider.model,
    }
