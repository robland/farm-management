/**
 * Editor of a draft version (scenarios S1 to S5): header, parcels, planting parameters,
 * calendar. Every value shows where it comes from; a documented range is never chosen by
 * the system; validation requires a complete calculation and no undecided AI suggestion.
 */

import {
  addAmounts, compareAmounts, durationError, fieldLabel, formatArea, formatDate, LAYOUT_LABELS, missingItems,
  parcelAvailability, PHASE_LABELS, PLANTING_FIELDS, PLANTING_METHOD_LABELS, percentToRatio, planRights, type PlanSection,
  ratioToPercent, SOURCE_KIND_LABELS, versionActions,
} from "@fms/shared";
import { type FormEvent, type ReactNode, useState } from "react";

import { ApiError, type ApiClient } from "../../api/client";
import type { AISuggestion, ComputeOutcome, MeFarm, PlanAllocation, PlanVersion, ProductionPlan } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Badge } from "../../ui/controls";
import { Button, Card, ErrorMessage, Field, Select, useBusy } from "../../ui/components";
import { errorText, type Planning, results, useAIRuns, versionWrite } from "./data";
import { SourceBadge } from "./SourceBadge";

const SECTIONS: { id: PlanSection; label: string }[] = [
  { id: "header", label: "En-tête" }, { id: "parcels", label: "Parcelles" },
  { id: "planting", label: "Plantation" }, { id: "calendar", label: "Calendrier" },
];

const decimalOk = (v: string) => !v.trim() || /^\d+([.,]\d+)?$/.test(v.trim());
const norm = (v: string) => v.trim().replace(",", ".").replace(/\s/g, "");

export function PlanEditor(props: { api: ApiClient; farm: MeFarm; plan: ProductionPlan; version: PlanVersion;
                                    planning: Planning; onChange: (v: PlanVersion) => void }): ReactNode {
  const { farmId, online } = useSync();
  const { notify } = useNotifications();
  const rights = planRights(props.farm.permissions);
  const { version } = props;
  const runs = useAIRuns(props.api, farmId, rights.ai || rights.edit);
  const suggestions = results(runs.data).flatMap((r) => r.suggestions).filter((s) => s.plan_version === version.id);
  const pending = suggestions.filter((s) => s.status === "suggested");
  const [outcome, setOutcome] = useState<ComputeOutcome | null>(null);
  const [needsChoice, setNeedsChoice] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const parcelName = (id: string) => {
    const p = props.planning.parcels.find((x) => x.id === id);
    return p ? p.code || p.name : "Parcelle";
  };
  const actions = versionActions(version, rights, { complete: outcome ? outcome.complete : null,
    pendingSuggestions: pending.length, hasDraft: true, planClosed: ["closed", "cancelled"].includes(props.plan.status) });
  const todo = outcome ? missingItems([...outcome.missing, ...outcome.errors.map((e) => ({ scope: e.scope, fields: [e.field],
                                                                                           reason: e.reason }))], parcelName) : [];
  const sectionState = (id: PlanSection) => todo.filter((t) => t.section === id).length;

  /** Writes and refresh: the server returns the fresh version (versioned with If-Match). */
  const write = (fn: () => Promise<PlanVersion | void>, done: string) => run(async () => {
    setError(null);
    try {
      const next = await fn();
      if (next) props.onChange(next);
      notify({ type: "success", farmId, text: done });
      return true;
    } catch (err) {
      setError(errorText(err));
      if (err instanceof ApiError) {
        const missing = (err.body.details as { missing?: ComputeOutcome["missing"] } | undefined)?.missing;
        if (missing) setOutcome({ complete: false, missing, errors: [], totals: {} });
      }
      return false;
    }
  });

  const prefill = () => void write(async () => {
    const report = await props.api.request<{ filled: string[]; needs_user_choice: string[]; version: PlanVersion }>(
      "POST", `/farms/${farmId}/plan-versions/${version.id}/prefill/`, {}, { headers: { "If-Match": String(version.version) } });
    setNeedsChoice(report.needs_user_choice);
    return report.version;
  }, "Champs vides remplis depuis la fiche variétale validée. Vos saisies sont conservées.");

  const compute = () => void write(async () => {
    const result = await props.api.request<ComputeOutcome>("POST", `/farms/${farmId}/plan-versions/${version.id}/compute/`, {});
    setOutcome(result);
    return props.api.request<PlanVersion>("GET", `/farms/${farmId}/plan-versions/${version.id}/`);
  }, "Calcul effectué.");

  const validate = () => void write(() => versionWrite(props.api, farmId, version, "POST", "validate", {}),
                                    "Plan validé : la version est figée et les parcelles sont réservées.");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-stone-500">
          {version.updated_at ? `Dernier enregistrement : ${formatDate(version.updated_at.slice(0, 10))}` : ""}
          {!online && " · Hors ligne : la modification d'un plan demande une connexion."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={busy || !online} onClick={prefill}>Pré-remplir depuis la fiche</Button>
          <Button variant="secondary" disabled={busy || !online} onClick={compute}>Calculer</Button>
          {actions.validate && (
            <Button disabled={busy || !online || actions.validateBlocked !== null} title={actions.validateBlocked ?? undefined}
                    onClick={validate}>Valider le plan</Button>
          )}
        </div>
      </div>
      {error && <ErrorMessage>{error}</ErrorMessage>}

      <div className="grid items-start gap-4 lg:grid-cols-[180px_1fr_280px]">
        <nav aria-label="Étapes du plan" className="flex flex-col gap-1 rounded-lg border border-stone-200 bg-white p-2 lg:sticky lg:top-4">
          {SECTIONS.map((s) => {
            const n = sectionState(s.id);
            return (
              <a key={s.id} href={`#plan-${s.id}`} className="flex min-h-10 items-center gap-2 rounded px-2 text-sm text-stone-800 hover:bg-stone-100">
                <span aria-hidden="true" className={`flex size-5 items-center justify-center rounded-full text-xs font-bold ${
                  !outcome ? "bg-stone-200 text-stone-600" : n ? "bg-amber-500 text-white" : "bg-green-700 text-white"}`}>
                  {!outcome ? "–" : n || "✓"}
                </span>
                {s.label}
                <span className="sr-only">{!outcome ? "" : n ? `, ${n} à compléter` : ", complet"}</span>
              </a>
            );
          })}
        </nav>

        <div className="flex flex-col gap-4">
          {pending.length > 0 || suggestions.length > 0 ? (
            <Suggestions api={props.api} suggestions={suggestions} busy={busy}
                         onDecided={async () => {
                           runs.reload();
                           props.onChange(await props.api.request<PlanVersion>("GET", `/farms/${farmId}/plan-versions/${version.id}/`));
                         }} />
          ) : null}
          <HeaderSection version={version} busy={busy} disabled={!actions.edit || !online}
                         onSave={(body) => void write(() => versionWrite(props.api, farmId, version, "PATCH", "", body), "En-tête enregistré.")} />
          <ParcelsSection version={version} plan={props.plan} planning={props.planning} busy={busy}
                          disabled={!actions.edit || !online} parcelName={parcelName}
                          onSave={(allocations) => void write(() => versionWrite(props.api, farmId, version, "PUT", "allocations",
                                                                                 { allocations }), "Parcelles enregistrées.")} />
          <PlantingSection version={version} needsChoice={needsChoice} busy={busy} disabled={!actions.edit || !online}
                           onSave={(changes) => void write(() => versionWrite(props.api, farmId, version, "PATCH", "planting-spec",
                                                                              changes), "Paramètres de plantation enregistrés.")} />
          <CalendarSection version={version} busy={busy} disabled={!actions.edit || !online}
                           onSave={(phases) => void write(() => versionWrite(props.api, farmId, version, "PUT", "phases",
                                                                             { phases }), "Calendrier enregistré.")} />
        </div>

        <aside aria-label="À compléter" className="flex flex-col gap-2 rounded-lg border border-stone-200 bg-white p-3 lg:sticky lg:top-4">
          <h3 className="font-semibold">{outcome ? `À compléter (${todo.length})` : "À compléter"}</h3>
          {!outcome ? (
            <p className="text-sm text-stone-500">Lancez « Calculer » : le moteur liste ce qui manque. Aucune valeur par défaut n'est ajoutée.</p>
          ) : todo.length === 0 ? (
            <p className="text-sm text-green-800">Rien ne manque : le plan peut être validé.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-stone-100 text-sm">
              {todo.map((t) => (
                <li key={t.key} className="py-1.5">
                  <a href={`#plan-${t.section}`} className="text-stone-800 hover:underline">
                    <strong>{t.where}</strong> : {t.what}{t.reason ? ` (${t.reason})` : ""}
                  </a>
                </li>
              ))}
            </ul>
          )}
          {actions.validateBlocked && actions.validate && (
            <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">Validation bloquée : {actions.validateBlocked}</p>
          )}
          {!rights.validate && (
            <p className="rounded-md bg-stone-100 p-2 text-xs text-stone-700">
              Vous préparez ce plan. La validation est réservée au droit « Valider les plans ».
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

function Section(props: { id: PlanSection; title: string; children: ReactNode; aside?: ReactNode }): ReactNode {
  return (
    <Card>
      <section id={`plan-${props.id}`} aria-labelledby={`plan-${props.id}-title`} className="flex scroll-mt-4 flex-col gap-3 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id={`plan-${props.id}-title`} className="font-semibold">{props.title}</h3>
          {props.aside}
        </div>
        {props.children}
      </section>
    </Card>
  );
}

const provenanceOf = (version: PlanVersion, path: string) => version.provenances.find((p) => p.field_path === path);

function HeaderSection(props: { version: PlanVersion; busy: boolean; disabled: boolean;
                                onSave: (body: Record<string, unknown>) => void }): ReactNode {
  const v = props.version;
  const [form, setForm] = useState({ planned_start_date: v.planned_start_date ?? "", target_yield_kg_per_ha: v.target_yield_kg_per_ha ?? "",
                                     objectives: v.objectives, constraints_notes: v.constraints_notes });
  const [invalid, setInvalid] = useState<string | undefined>();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!decimalOk(form.target_yield_kg_per_ha)) {
      setInvalid("Nombre positif en kg/ha.");
      return;
    }
    setInvalid(undefined);
    props.onSave({ planned_start_date: form.planned_start_date || null,
                   target_yield_kg_per_ha: form.target_yield_kg_per_ha.trim() ? norm(form.target_yield_kg_per_ha) : null,
                   objectives: form.objectives, constraints_notes: form.constraints_notes });
  };
  return (
    <Section id="header" title="En-tête">
      <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2" aria-label="En-tête du plan">
        <Field label="Date de début" type="date" value={form.planned_start_date} disabled={props.disabled}
               onChange={(e) => setForm({ ...form, planned_start_date: e.target.value })} />
        <Field label="Rendement visé (kg/ha, facultatif)" inputMode="decimal" value={form.target_yield_kg_per_ha} error={invalid}
               disabled={props.disabled} onChange={(e) => setForm({ ...form, target_yield_kg_per_ha: e.target.value })} />
        <Field label="Objectifs" value={form.objectives} disabled={props.disabled}
               onChange={(e) => setForm({ ...form, objectives: e.target.value })} />
        <Field label="Contraintes" value={form.constraints_notes} disabled={props.disabled}
               onChange={(e) => setForm({ ...form, constraints_notes: e.target.value })} />
        {!props.disabled && <div><Button type="submit" variant="secondary" disabled={props.busy}>Enregistrer l'en-tête</Button></div>}
      </form>
    </Section>
  );
}

type AllocationForm = { parcel: string; allocated_area_m2: string; non_plantable_area_m2: string; plot_length_m: string;
                        plot_width_m: string; notes: string };

const toForm = (a: PlanAllocation): AllocationForm => ({
  parcel: a.parcel, allocated_area_m2: a.allocated_area_m2.replace(/\.?0+$/, ""),
  non_plantable_area_m2: a.non_plantable_area_m2.replace(/\.?0+$/, ""),
  plot_length_m: (a.plot_length_m ?? "").replace(/\.?0+$/, ""), plot_width_m: (a.plot_width_m ?? "").replace(/\.?0+$/, ""),
  notes: a.notes });

function ParcelsSection(props: { version: PlanVersion; plan: ProductionPlan; planning: Planning; busy: boolean; disabled: boolean;
                                 parcelName: (id: string) => string; onSave: (allocations: Record<string, unknown>[]) => void }): ReactNode {
  const [rows, setRows] = useState<AllocationForm[]>(() => props.version.allocations.map(toForm));
  const [errors, setErrors] = useState<Record<number, string>>({});
  const campaign = props.planning.campaigns.find((c) => c.id === props.plan.campaign);
  const period = { start: props.version.planned_start_date ?? campaign?.start_date ?? "",
                   end: props.version.planned_end_date ?? campaign?.end_date ?? "" };
  const setRow = (i: number, patch: Partial<AllocationForm>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const check = (): Record<number, string> => {
    const found: Record<number, string> = {};
    rows.forEach((r, i) => {
      if (!r.parcel) found[i] = "Parcelle obligatoire.";
      else if (!r.allocated_area_m2.trim() || !decimalOk(r.allocated_area_m2) || compareAmounts(norm(r.allocated_area_m2), 0) <= 0) {
        found[i] = "Surface allouée en m², nombre positif.";
      } else if (![r.non_plantable_area_m2, r.plot_length_m, r.plot_width_m].every(decimalOk)) found[i] = "Nombres positifs en m.";
      else if (r.non_plantable_area_m2.trim() && compareAmounts(norm(r.non_plantable_area_m2), norm(r.allocated_area_m2)) > 0) {
        found[i] = "La surface non plantable dépasse la surface allouée.";
      }
    });
    return found;
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found = check();
    setErrors(found);
    if (Object.keys(found).length) return;
    props.onSave(rows.map((r) => ({
      parcel: r.parcel, allocated_area_m2: norm(r.allocated_area_m2), non_plantable_area_m2: r.non_plantable_area_m2.trim() ? norm(r.non_plantable_area_m2) : "0",
      plot_length_m: r.plot_length_m.trim() ? norm(r.plot_length_m) : null, plot_width_m: r.plot_width_m.trim() ? norm(r.plot_width_m) : null,
      notes: r.notes })));
  };
  const total = addAmounts(...rows.map((r) => (decimalOk(r.allocated_area_m2) ? norm(r.allocated_area_m2) || "0" : "0")));

  return (
    <Section id="parcels" title="Parcelles" aside={<span className="text-xs text-stone-500">Total : {formatArea(total)}</span>}>
      <form onSubmit={submit} noValidate aria-label="Parcelles du plan" className="flex flex-col gap-3">
        {rows.length === 0 && <p className="text-sm text-stone-500">Aucune parcelle affectée.</p>}
        {rows.map((r, i) => {
          const parcel = props.planning.parcels.find((p) => p.id === r.parcel);
          const availability = parcel && period.start && period.end
            ? parcelAvailability(parcel.area_m2, props.planning.cycles, parcel.id, period, props.plan.id) : null;
          const over = availability && decimalOk(r.allocated_area_m2) && r.allocated_area_m2.trim()
            && compareAmounts(norm(r.allocated_area_m2), availability.available) > 0;
          return (
            <div key={i} className="flex flex-col gap-2 rounded-md border border-stone-200 p-3">
              <div className="grid gap-3 sm:grid-cols-5">
                <Select label="Parcelle" value={r.parcel} disabled={props.disabled} onChange={(e) => setRow(i, { parcel: e.target.value })}
                        options={props.planning.parcels.map((p) => ({ value: p.id, label: `${p.code || p.name} · ${formatArea(p.area_m2)}` }))} />
                <Field label="Surface allouée (m²)" inputMode="decimal" value={r.allocated_area_m2} disabled={props.disabled}
                       onChange={(e) => setRow(i, { allocated_area_m2: e.target.value })} />
                <Field label="dont non plantable (m²)" inputMode="decimal" value={r.non_plantable_area_m2} disabled={props.disabled}
                       onChange={(e) => setRow(i, { non_plantable_area_m2: e.target.value })} />
                <Field label="Longueur (m, facultatif)" inputMode="decimal" value={r.plot_length_m} disabled={props.disabled}
                       onChange={(e) => setRow(i, { plot_length_m: e.target.value })} />
                <Field label="Largeur (m, facultatif)" inputMode="decimal" value={r.plot_width_m} disabled={props.disabled}
                       onChange={(e) => setRow(i, { plot_width_m: e.target.value })} />
              </div>
              {errors[i] && <p role="alert" className="text-sm text-red-700">{errors[i]}</p>}
              {over && availability && parcel && (
                <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-900">
                  <strong>{props.parcelName(parcel.id)} est déjà occupée sur cette période.</strong> Occupé : {formatArea(availability.occupied)} ·
                  demandé : {formatArea(norm(r.allocated_area_m2))} · surface de la parcelle : {formatArea(parcel.area_m2)}. Disponible :
                  {" "}{formatArea(availability.available)}. Pour valider : réduire la surface, décaler les dates ou choisir une autre parcelle.
                </p>
              )}
              {!props.disabled && (
                <div><Button variant="ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Retirer cette parcelle</Button></div>
              )}
            </div>
          );
        })}
        <p className="text-xs text-stone-500">
          Longueur et largeur permettent le calcul géométrique du nombre de plants réel ; sans elles, il est égal au
          nombre théorique sur la surface plantable.
        </p>
        {!props.disabled && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setRows([...rows, { parcel: "", allocated_area_m2: "", non_plantable_area_m2: "",
                                                                         plot_length_m: "", plot_width_m: "", notes: "" }])}>
              Ajouter une parcelle
            </Button>
            <Button type="submit" variant="secondary" disabled={props.busy}>Enregistrer les parcelles</Button>
          </div>
        )}
      </form>
    </Section>
  );
}

function PlantingSection(props: { version: PlanVersion; needsChoice: string[]; busy: boolean; disabled: boolean;
                                  onSave: (changes: Record<string, unknown>) => void }): ReactNode {
  const spec = props.version.planting_spec ?? {};
  const initial = Object.fromEntries(PLANTING_FIELDS.map((f) => {
    const raw = spec[f.key];
    const text = raw === null || raw === undefined ? "" : String(raw);
    return [f.key, f.kind === "percent" ? ratioToPercent(text) : f.kind === "decimal" ? text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") : text];
  })) as Record<string, string>;
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const shown = PLANTING_FIELDS.filter((f) => (!f.method || form.planting_method === f.method) && (!f.layout || form.layout === f.layout));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found: Record<string, string> = {};
    const changes: Record<string, unknown> = {};
    for (const f of PLANTING_FIELDS) {
      const value = (form[f.key] ?? "").trim();
      if (value === (initial[f.key] ?? "")) continue;
      if (f.kind === "choice") changes[f.key] = value || (f.key === "layout" ? "single_row" : "");
      else if (!value) changes[f.key] = null;
      else if (f.kind === "integer") {
        if (!/^\d+$/.test(value) || Number(value) < 1) found[f.key] = "Nombre entier positif.";
        else changes[f.key] = Number(value);
      } else if (f.kind === "percent") {
        const ratio = percentToRatio(value);
        if (ratio === undefined) found[f.key] = "Pourcentage (au plus 2 décimales).";
        else changes[f.key] = ratio;
      } else if (!decimalOk(value)) found[f.key] = "Nombre positif.";
      else changes[f.key] = norm(value);
    }
    setErrors(found);
    if (Object.keys(found).length || Object.keys(changes).length === 0) return;
    props.onSave(changes);
  };

  return (
    <Section id="planting" title="Paramètres de plantation"
             aside={<span className="text-xs text-stone-500">Valeurs de la fiche variétale validée ou saisies par vous</span>}>
      <form onSubmit={submit} noValidate aria-label="Paramètres de plantation" className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-3">
          {shown.map((f) => {
            const provenance = provenanceOf(props.version, `planting_spec.${f.key}`);
            const choose = props.needsChoice.includes(f.key) && !(form[f.key] ?? "").trim();
            return (
              <div key={f.key} className={`flex flex-col gap-1 ${choose ? "rounded-md border border-amber-400 bg-amber-50 p-2" : ""}`}>
                {f.kind === "choice" ? (
                  <Select label={f.label} value={form[f.key] ?? ""} disabled={props.disabled}
                          onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                          options={Object.entries(f.key === "layout" ? LAYOUT_LABELS : PLANTING_METHOD_LABELS)
                            .map(([value, text]) => ({ value, label: text }))} />
                ) : (
                  <Field label={`${f.label}${f.unit ? ` (${f.unit})` : ""}`} inputMode="decimal" value={form[f.key] ?? ""}
                         disabled={props.disabled} error={errors[f.key]}
                         placeholder={choose ? "À choisir dans la plage de la fiche" : ""}
                         onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                )}
                {choose ? (
                  <span className="text-xs text-amber-900">La fiche donne une plage : le système ne choisit pas à votre place.</span>
                ) : provenance ? <SourceBadge kind={provenance.source_kind} note={provenance.note} /> : null}
              </div>
            );
          })}
        </div>
        <p className="text-xs text-stone-500">
          Origine des valeurs : {Object.entries(SOURCE_KIND_LABELS).map(([kind]) => (
            <span key={kind} className="mr-1"><SourceBadge kind={kind} /></span>))}
        </p>
        {!props.disabled && <div><Button type="submit" variant="secondary" disabled={props.busy}>Enregistrer les paramètres</Button></div>}
      </form>
    </Section>
  );
}

function CalendarSection(props: { version: PlanVersion; busy: boolean; disabled: boolean;
                                  onSave: (phases: { phase_code: string; duration_days: number | null }[]) => void }): ReactNode {
  const ordered = [...props.version.phases].sort((a, b) => a.sequence - b.sequence);
  const [rows, setRows] = useState(ordered.map((p) => ({ code: p.phase_code, days: p.duration_days === null ? "" : String(p.duration_days) })));
  const [error, setError] = useState<string | null>(null);
  const dated = new Map(ordered.map((p) => [p.phase_code, p]));
  const codes = [...new Set([...Object.keys(PHASE_LABELS), ...rows.map((r) => r.code)])].filter(Boolean);
  const move = (i: number, delta: number) => {
    const next = [...rows];
    const [row] = next.splice(i, 1);
    if (row) next.splice(i + delta, 0, row);
    setRows(next);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const bad = rows.find((r) => !r.code || durationError(r.days));
    const duplicated = new Set(rows.map((r) => r.code)).size !== rows.length;
    if (bad || duplicated) {
      setError(duplicated ? "Chaque phase n'apparaît qu'une fois." : bad && !bad.code ? "Choisissez la phase." : "Durée : nombre entier de jours.");
      return;
    }
    setError(null);
    props.onSave(rows.map((r) => ({ phase_code: r.code, duration_days: r.days.trim() ? Number(r.days) : null })));
  };
  return (
    <Section id="calendar" title="Calendrier cultural"
             aside={<span className="text-xs text-stone-500">Début : {props.version.planned_start_date
               ? formatDate(props.version.planned_start_date) : "à saisir dans l'en-tête"}</span>}>
      <form onSubmit={submit} noValidate aria-label="Calendrier cultural" className="flex flex-col gap-2">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-stone-500">
              <th className="p-1">#</th><th className="p-1">Phase</th><th className="p-1">Durée (jours)</th>
              <th className="p-1">Dates calculées</th><th className="p-1">Origine</th><th className="p-1"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const d = dated.get(r.code);
              const provenance = provenanceOf(props.version, `phases.${r.code}.duration_days`);
              return (
                <tr key={i} className={`border-t border-stone-100 ${!r.days.trim() ? "bg-amber-50" : ""}`}>
                  <td className="p-1">{i + 1}</td>
                  <td className="p-1">
                    <select aria-label={`Phase ${i + 1}`} value={r.code} disabled={props.disabled}
                            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))}
                            className="min-h-9 rounded-md border border-stone-300 bg-white px-2">
                      <option value="">Choisir…</option>
                      {codes.map((c) => <option key={c} value={c}>{PHASE_LABELS[c] ?? c}</option>)}
                    </select>
                  </td>
                  <td className="p-1">
                    <input aria-label={`Durée de la phase ${i + 1} (jours)`} inputMode="numeric" value={r.days} disabled={props.disabled}
                           placeholder="à saisir" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, days: e.target.value } : x)))}
                           className="min-h-9 w-24 rounded-md border border-stone-300 px-2" />
                  </td>
                  <td className="p-1 text-xs text-stone-600">
                    {d?.start_date && d.end_date ? `${formatDate(d.start_date)} → ${formatDate(d.end_date)}` : "—"}
                  </td>
                  <td className="p-1">{provenance ? <SourceBadge kind={provenance.source_kind} /> : null}</td>
                  <td className="p-1 whitespace-nowrap">
                    {!props.disabled && (
                      <>
                        <button type="button" aria-label="Monter" disabled={i === 0} onClick={() => move(i, -1)}
                                className="min-h-9 px-2 disabled:opacity-30">↑</button>
                        <button type="button" aria-label="Descendre" disabled={i === rows.length - 1} onClick={() => move(i, 1)}
                                className="min-h-9 px-2 disabled:opacity-30">↓</button>
                        <button type="button" aria-label={`Retirer ${fieldLabel(`phases.${r.code}`).replace("Durée : ", "")}`}
                                onClick={() => setRows(rows.filter((_, j) => j !== i))} className="min-h-9 px-2 text-red-700">✕</button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="text-xs text-stone-500">
          Une durée non entière dans la fiche n'est pas arrondie : elle reste à saisir. Les dates sont calculées par le moteur.
        </p>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        {!props.disabled && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setRows([...rows, { code: "", days: "" }])}>Ajouter une phase</Button>
            <Button type="submit" variant="secondary" disabled={props.busy}>Enregistrer le calendrier</Button>
          </div>
        )}
      </form>
    </Section>
  );
}

/** AI proposals: each is accepted, modified or rejected by a person (FR-104, FR-105). */
function Suggestions(props: { api: ApiClient; suggestions: AISuggestion[]; busy: boolean; onDecided: () => Promise<void> }): ReactNode {
  const { farmId, online } = useSync();
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const pending = props.suggestions.filter((s) => s.status === "suggested");
  const decide = (s: AISuggestion, decision: "accept" | "reject" | "modify") => void run(async () => {
    setError(null);
    try {
      await props.api.request("POST", `/farms/${farmId}/ai/suggestions/${s.id}/decide/`,
                              decision === "modify" ? { decision, value: value.trim().replace(",", ".") } : { decision });
      setEditing(null);
      await props.onDecided();
    } catch (err) {
      setError(errorText(err));
    }
  });
  return (
    <Card>
      <section aria-labelledby="ai-title" className="flex flex-col gap-2 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="ai-title" className="font-semibold">Propositions de l'IA ({pending.length} à trancher)</h3>
          <span className="text-xs text-stone-500">L'IA propose, vous décidez. Rien n'est appliqué sans votre choix.</span>
        </div>
        {error && <ErrorMessage>{error}</ErrorMessage>}
        <ul className="divide-y divide-stone-100">
          {props.suggestions.map((s) => (
            <li key={s.id} className="grid gap-2 py-2 sm:grid-cols-[200px_1fr_auto] sm:items-center">
              <span><span className="block font-medium">{fieldLabel(s.field_path)}</span><SourceBadge kind="ai_suggestion" /></span>
              <span className="text-sm">
                <strong>{String(s.value ?? "—")}</strong>
                {s.rationale && <span className="block text-xs text-stone-600">{s.rationale}</span>}
                <span className="block text-xs text-violet-800">Aucune citation retrouvée dans la fiche : recommandation de l'IA, pas donnée documentaire.</span>
              </span>
              {s.status !== "suggested" ? (
                <Badge tone={s.status === "rejected" ? "muted" : "ok"}>
                  {s.status === "accepted" ? "Acceptée" : s.status === "modified" ? "Modifiée" : "Rejetée"}
                </Badge>
              ) : editing === s.id ? (
                <span className="flex flex-wrap items-center gap-2">
                  <input aria-label={`Nouvelle valeur : ${fieldLabel(s.field_path)}`} value={value} onChange={(e) => setValue(e.target.value)}
                         className="min-h-9 w-28 rounded-md border border-stone-300 px-2" />
                  <Button disabled={busy || !value.trim()} onClick={() => decide(s, "modify")}>Enregistrer</Button>
                  <Button variant="ghost" onClick={() => setEditing(null)}>Annuler</Button>
                </span>
              ) : (
                <span className="flex flex-wrap gap-2">
                  <Button disabled={busy || props.busy || !online} onClick={() => decide(s, "accept")}>Accepter</Button>
                  <Button variant="secondary" disabled={!online} onClick={() => { setValue(String(s.value ?? "")); setEditing(s.id); }}>Modifier…</Button>
                  <Button variant="secondary" disabled={busy || !online} className="text-red-700" onClick={() => decide(s, "reject")}>Rejeter</Button>
                </span>
              )}
            </li>
          ))}
        </ul>
        <p className="text-xs text-stone-500">
          Les valeurs reprises d'une donnée validée de la fiche ne sont pas listées ici : elles portent le badge « Source
          documentaire » dans les paramètres. Le nombre de plants et les semences sont toujours calculés par le moteur.
        </p>
      </section>
    </Card>
  );
}
