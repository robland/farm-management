/**
 * Campaigns tab: a campaign with its production plans and the occupation of the parcels;
 * a plan opens its editor (draft) or its results (validated). FR-030 to FR-035.
 */

import {
  addAmounts, budgetTotals, CAMPAIGN_STATUS_LABELS, CYCLE_STATUS_LABELS, formatArea, formatDate, formatMoney, label,
  monthColumns, normalizeBudgetRows, PHASE_LABELS, PLAN_STATUS_LABELS, planRights, timelineBar, todayIso,
} from "@fms/shared";
import { type FormEvent, type ReactNode, useEffect, useId, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { Campaign, MeFarm, Parcel, PlanVersion, ProductionPlan } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Badge } from "../../ui/controls";
import { Button, Card, EmptyState, ErrorMessage, Field, Loading, Select, useBusy } from "../../ui/components";
import { errorText, shownVersion, usePlanning, useRemote, useVarieties } from "./data";
import { PlanView } from "./PlanView";

const STATUS_TONE = { draft: "neutral", validated: "ok", in_progress: "info", closed: "muted", cancelled: "muted" } as const;

export function CampaignsPage(props: { api: ApiClient; farm: MeFarm }): ReactNode {
  const { farmId } = useSync();
  const rights = planRights(props.farm.permissions);
  const planning = usePlanning();
  const [campaignId, setCampaignId] = useState<string>("");
  const [openPlan, setOpenPlan] = useState<string | null>(null);
  const [creating, setCreating] = useState<null | "campaign" | "plan">(null);
  const today = todayIso();
  const current = planning.campaigns.find((c) => c.id === campaignId)
    ?? planning.campaigns.find((c) => c.status === "active") ?? planning.campaigns[0];
  const plans = planning.plans.filter((p) => p.campaign === current?.id);
  const canBudget = props.farm.permissions.includes("finance.view");
  const budget = useRemote<Record<string, string | number | null>[]>(
    props.api, canBudget && current ? `/farms/${farmId}/budget-lines/report/?campaign=${current.id}` : null,
    `fms.budget.${farmId}.${current?.id ?? ""}`);
  const budgetTotal = budgetTotals(normalizeBudgetRows(budget.data ?? []))[0];

  useEffect(() => {
    if (current && current.id !== campaignId) setCampaignId(current.id);
  }, [current, campaignId]);

  const plan = planning.plans.find((p) => p.id === openPlan);
  if (plan) {
    return <PlanView api={props.api} farm={props.farm} plan={plan} planning={planning} onBack={() => setOpenPlan(null)} />;
  }
  if (planning.loading) return <Loading />;

  const versionOf = (p: ProductionPlan) => shownVersion(p, planning.versions);
  const engaged = addAmounts(...planning.cycles.filter((c) => plans.some((p) => p.id === c.plan) && c.status !== "cancelled")
    .map((c) => c.area_m2));
  const planTasks = planning.tasks.filter((t) => plans.some((p) => p.id === t.plan) && t.status !== "cancelled");

  return (
    <section className="flex flex-col gap-4" aria-label="Campagnes">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {planning.campaigns.length > 0 ? (
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-72">
              <Select label="Campagne" value={current?.id ?? ""} onChange={(e) => setCampaignId(e.target.value)}
                      placeholder="Choisir…"
                      options={planning.campaigns.map((c) => ({ value: c.id,
                        label: c.status === "active" ? c.name : `${c.name} (${label(CAMPAIGN_STATUS_LABELS, c.status).toLowerCase()})` }))} />
            </div>
            {current && (
              <p className="flex items-center gap-2 pb-2 text-sm text-stone-600">
                <Badge tone={current.status === "active" ? "info" : current.status === "closed" ? "muted" : "neutral"}>
                  {label(CAMPAIGN_STATUS_LABELS, current.status)}
                </Badge>
                {formatDate(current.start_date)} → {formatDate(current.end_date)}
              </p>
            )}
          </div>
        ) : <h2 className="text-lg font-semibold">Campagnes</h2>}
        {rights.edit && !creating && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setCreating("campaign")}>Nouvelle campagne</Button>
            {current && current.status !== "closed" && <Button onClick={() => setCreating("plan")}>+ Nouveau plan</Button>}
          </div>
        )}
      </div>

      {creating === "campaign" && (
        <CampaignForm api={props.api} onDone={(id) => { setCreating(null); if (id) setCampaignId(id); }} />
      )}
      {creating === "plan" && current && (
        <NewPlanDialog api={props.api} farm={props.farm} campaign={current} parcels={planning.parcels}
                       onClose={() => setCreating(null)} onCreated={(id) => { setCreating(null); setOpenPlan(id); }} />
      )}

      {!current ? (
        <EmptyState hint={rights.edit ? "Une campagne regroupe les plans de production d'une saison." : undefined}>
          Aucune campagne pour cette exploitation.
        </EmptyState>
      ) : (
        <>
          <section aria-label="Synthèse" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="p-3"><p className="text-xs text-stone-500">Plans</p>
              <p className="text-xl font-semibold">{plans.length}</p>
              <p className="text-xs text-stone-500">
                {plans.filter((p) => p.status === "in_progress" || p.status === "validated").length} validés ·{" "}
                {plans.filter((p) => p.status === "draft").length} brouillons
              </p></Card>
            <Card className="p-3"><p className="text-xs text-stone-500">Surface engagée</p>
              <p className="text-xl font-semibold">{formatArea(engaged)}</p>
              <p className="text-xs text-stone-500">plans validés seulement</p></Card>
            <Card className="p-3"><p className="text-xs text-stone-500">Tâches de la campagne</p>
              <p className="text-xl font-semibold">{planTasks.filter((t) => t.status === "done").length} / {planTasks.length}</p>
              <p className="text-xs text-stone-500">terminées</p></Card>
            {canBudget && (
              <Card className="p-3"><p className="text-xs text-stone-500">Budget de la campagne</p>
                <p className="text-lg font-semibold tabular-nums">
                  {budgetTotal ? `${formatMoney(budgetTotal.actual, budgetTotal.currency)} / ${formatMoney(budgetTotal.planned, budgetTotal.currency)}` : "—"}
                </p>
                <p className="text-xs text-stone-500">réalisé / prévu (onglet Finances)</p></Card>
            )}
          </section>

          <Card>
            <h3 className="border-b border-stone-200 p-3 font-semibold">Plans de production</h3>
            {plans.length === 0 ? (
              <p className="p-3 text-sm text-stone-500">Aucun plan dans cette campagne.</p>
            ) : (
              <ul className="divide-y divide-stone-100">
                {plans.map((p) => {
                  const v = versionOf(p);
                  const area = addAmounts(...(v?.allocations ?? []).map((a) => a.allocated_area_m2));
                  const phase = (v?.phases ?? []).find((ph) => ph.start_date && ph.end_date
                    && ph.start_date <= today && today <= ph.end_date);
                  return (
                    <li key={p.id}>
                      <button type="button" onClick={() => setOpenPlan(p.id)}
                              className="grid w-full gap-2 p-3 text-left hover:bg-stone-50 focus-visible:outline-2
                                         focus-visible:outline-green-700 sm:grid-cols-[1fr_140px_200px]">
                        <span>
                          <span className="block font-semibold">{p.name}</span>
                          <span className="text-xs text-stone-500">
                            {p.variety_name} · {formatArea(area)}{v ? ` · version ${v.number}` : ""}
                          </span>
                        </span>
                        <span className="flex flex-wrap gap-1">
                          <Badge tone={STATUS_TONE[p.status as keyof typeof STATUS_TONE] ?? "neutral"}>
                            {label(PLAN_STATUS_LABELS, p.status)}
                          </Badge>
                          {v?.origin === "ai_draft" && v.status === "draft" && <Badge tone="info">Assisté IA</Badge>}
                        </span>
                        <span className="text-xs text-stone-500">
                          {phase ? `Phase : ${phase.phase_code ? phaseName(phase.phase_code) : ""} (jusqu'au ${formatDate(phase.end_date ?? "")})`
                            : v?.status === "draft" ? "Brouillon en préparation" : ""}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <Occupation campaign={current} parcels={planning.parcels} cycles={planning.cycles}
                      plans={planning.plans} versions={planning.versions} campaignPlans={plans} />
        </>
      )}
    </section>
  );
}

const phaseName = (code: string) => PHASE_LABELS[code] ?? code;

/** Gantt of the crop cycles per parcel; drafts are hatched (the parcel is not reserved). */
function Occupation(props: { campaign: Campaign; parcels: Parcel[]; cycles: { plan: string; parcel: string; area_m2: string;
                               start_date: string; end_date: string; status: string; id: string }[];
                             plans: ProductionPlan[]; versions: PlanVersion[]; campaignPlans: ProductionPlan[] }): ReactNode {
  const range = { start: props.campaign.start_date, end: props.campaign.end_date };
  const months = monthColumns(range);
  const today = timelineBar(range, todayIso(), todayIso());
  const drafts = props.campaignPlans.flatMap((p) => {
    const draft = props.versions.find((v) => v.plan === p.id && v.status === "draft");
    if (!draft?.planned_start_date) return [];
    return draft.allocations.map((a) => ({ plan: p, parcel: a.parcel, area: a.allocated_area_m2,
                                           start: draft.planned_start_date ?? "", end: draft.planned_end_date ?? props.campaign.end_date }));
  });
  const shownParcels = props.parcels.filter((parcel) => props.cycles.some((c) => c.parcel === parcel.id && c.status !== "cancelled"
    && timelineBar(range, c.start_date, c.end_date)) || drafts.some((d) => d.parcel === parcel.id));
  const planName = (id: string) => props.plans.find((p) => p.id === id)?.name ?? "Autre plan";

  return (
    <Card className="p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">Occupation des parcelles</h3>
        <span className="text-xs text-stone-500">Cycles culturaux · aujourd'hui : {formatDate(todayIso())}</span>
      </div>
      {shownParcels.length === 0 ? (
        <p className="mt-2 text-sm text-stone-500">Aucune parcelle engagée sur la période de la campagne.</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <div className="min-w-[640px]">
            <div className="grid text-xs text-stone-500" style={{ gridTemplateColumns: `140px repeat(${months.length}, 1fr)` }}>
              <span />
              {months.map((m) => <span key={m.start} className="border-l border-stone-100 px-1 py-1 text-center">{m.label}</span>)}
            </div>
            {shownParcels.map((parcel) => (
              <div key={parcel.id} className="grid items-center border-t border-stone-100"
                   style={{ gridTemplateColumns: "140px 1fr" }}>
                <span className="py-2 text-sm font-medium">{parcel.code || parcel.name} · {formatArea(parcel.area_m2)}</span>
                <div className="relative h-10">
                  {props.cycles.filter((c) => c.parcel === parcel.id && c.status !== "cancelled").map((c) => {
                    const bar = timelineBar(range, c.start_date, c.end_date);
                    return bar && (
                      <span key={c.id} title={`${planName(c.plan)} · ${label(CYCLE_STATUS_LABELS, c.status)}`}
                            className="absolute top-2 h-6 truncate rounded bg-green-700 px-1.5 text-xs leading-6 text-white"
                            style={{ left: `${bar.left}%`, width: `${bar.width}%` }}>
                        {planName(c.plan)} · {formatArea(c.area_m2)}
                      </span>
                    );
                  })}
                  {drafts.filter((d) => d.parcel === parcel.id).map((d) => {
                    const bar = timelineBar(range, d.start, d.end);
                    return bar && (
                      <span key={`${d.plan.id}-${d.parcel}`} title={`${d.plan.name} · brouillon`}
                            className="absolute top-2 h-6 truncate rounded border border-dashed border-amber-600 bg-amber-100/80 px-1.5
                                       text-xs leading-6 text-amber-900"
                            style={{ left: `${bar.left}%`, width: `${bar.width}%` }}>
                        {d.plan.name} · brouillon · {formatArea(d.area)}
                      </span>
                    );
                  })}
                  {today && <span aria-hidden="true" className="absolute inset-y-0 w-0.5 bg-red-700" style={{ left: `${today.left}%` }} />}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      <p className="mt-2 text-xs text-stone-500">
        Plein : cycle d'un plan validé. Pointillés : brouillon, la parcelle n'est pas encore réservée. Trait rouge :
        aujourd'hui.
      </p>
    </Card>
  );
}

function CampaignForm(props: { api: ApiClient; onDone: (id?: string) => void }): ReactNode {
  const { farmId, syncNow } = useSync();
  const { notify } = useNotifications();
  const [form, setForm] = useState({ name: "", start_date: "", end_date: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof typeof form, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const found: typeof errors = {};
      if (!form.name.trim()) found.name = "Nom obligatoire.";
      if (!form.start_date) found.start_date = "Date de début obligatoire.";
      if (!form.end_date) found.end_date = "Date de fin obligatoire.";
      else if (form.start_date && form.end_date < form.start_date) found.end_date = "Avant la date de début.";
      setErrors(found);
      if (Object.keys(found).length) return;
      try {
        const created = await props.api.request<{ id: string }>("POST", `/farms/${farmId}/campaigns/`,
                                                                { ...form, name: form.name.trim() });
        notify({ type: "success", farmId, text: `Campagne « ${form.name.trim()} » créée.` });
        await syncNow();
        props.onDone(created.id);
      } catch (err) {
        setError(errorText(err));
      }
    });
  };
  return (
    <Card>
      <form onSubmit={submit} noValidate aria-label="Nouvelle campagne" className="grid gap-3 p-4 sm:grid-cols-3">
        <h3 className="font-medium sm:col-span-3">Nouvelle campagne</h3>
        <Field label="Nom" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name}
               hint="ex. Saison sèche 2027" />
        <Field label="Début" type="date" value={form.start_date} error={errors.start_date}
               onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        <Field label="Fin" type="date" value={form.end_date} error={errors.end_date}
               onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        {error && <div className="sm:col-span-3"><ErrorMessage>{error}</ErrorMessage></div>}
        <div className="flex gap-2 sm:col-span-3">
          <Button type="submit" disabled={busy}>{busy ? "Création…" : "Créer la campagne"}</Button>
          <Button variant="secondary" onClick={() => props.onDone()}>Annuler</Button>
        </div>
      </form>
    </Card>
  );
}

/** Manual plan, or a draft prepared by the AI; the AI never validates (FR-031, FR-105). */
function NewPlanDialog(props: { api: ApiClient; farm: MeFarm; campaign: Campaign; parcels: Parcel[];
                                onClose: () => void; onCreated: (planId: string) => void }): ReactNode {
  const { farmId, syncNow, online } = useSync();
  const { notify } = useNotifications();
  const rights = planRights(props.farm.permissions);
  const varieties = useVarieties(props.api, props.farm.organization_id);
  const status = useRemote<{ available: boolean; reason?: string }>(props.api, rights.ai ? "/ai/status/" : null, "fms.ai-status");
  const [mode, setMode] = useState<"manual" | "ai">("manual");
  const [form, setForm] = useState({ name: "", variety: "", parcel: "", allocated_area_m2: "", non_plantable_area_m2: "",
                                     planned_start_date: "", objectives: "", constraints: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof typeof form, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const titleId = useId();
  const aiAvailable = rights.ai && status.data?.available === true && online;
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && props.onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [props]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const found: typeof errors = {};
      if (!form.variety) found.variety = "Variété obligatoire.";
      if (mode === "manual" && !form.name.trim()) found.name = "Nom obligatoire.";
      if (mode === "ai") {
        if (!form.parcel) found.parcel = "Parcelle obligatoire.";
        if (!/^\d+([.,]\d+)?$/.test(form.allocated_area_m2.trim())) found.allocated_area_m2 = "Surface en m², nombre positif.";
        if (!form.planned_start_date) found.planned_start_date = "Date de début obligatoire.";
      }
      setErrors(found);
      if (Object.keys(found).length) return;
      setError(null);
      try {
        let planId: string;
        if (mode === "manual") {
          const plan = await props.api.request<{ id: string }>("POST", `/farms/${farmId}/plans/`,
            { campaign: props.campaign.id, variety: form.variety, name: form.name.trim() });
          planId = plan.id;
        } else {
          const ai = await props.api.request<{ plan_version: string | null; status: string; error_message: string }>(
            "POST", `/farms/${farmId}/ai/plan-drafts/`, {
              campaign: props.campaign.id, variety: form.variety, parcel: form.parcel, name: form.name.trim(),
              allocated_area_m2: form.allocated_area_m2.replace(",", "."),
              ...(form.non_plantable_area_m2.trim() ? { non_plantable_area_m2: form.non_plantable_area_m2.replace(",", ".") } : {}),
              planned_start_date: form.planned_start_date, objectives: form.objectives, constraints: form.constraints });
          if (!ai.plan_version) throw new Error(ai.error_message || "L'IA n'a pas produit de brouillon : utilisez la saisie manuelle.");
          const version = await props.api.request<{ plan: string }>("GET", `/farms/${farmId}/plan-versions/${ai.plan_version}/`);
          planId = version.plan;
        }
        notify({ type: "success", farmId, text: mode === "ai" ? "Brouillon préparé par l'IA : chaque proposition est à trancher."
          : "Plan créé (version 1, brouillon)." });
        await syncNow();
        props.onCreated(planId);
      } catch (err) {
        setError(errorText(err));
      }
    });
  };

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center overflow-y-auto bg-black/40 p-4 sm:items-center"
         onClick={(e) => e.target === e.currentTarget && props.onClose()}>
      <form role="dialog" aria-modal="true" aria-labelledby={titleId} onSubmit={submit} noValidate
            className="flex w-full max-w-lg flex-col gap-3 rounded-lg bg-white p-4 shadow-lg">
        <h2 id={titleId} className="font-semibold">Nouveau plan · {props.campaign.name}</h2>
        <div role="radiogroup" aria-label="Mode de création" className="grid gap-2">
          {([["manual", "Saisie manuelle", "Vous renseignez la variété, les parcelles, les paramètres et le calendrier. Pré-remplissage possible depuis la fiche variétale validée."],
             ["ai", "Brouillon assisté par l'IA", "L'IA lit la fiche technique et propose des valeurs sourcées. Chaque proposition est à accepter, modifier ou rejeter ; elle ne valide jamais le plan."]] as const)
            .map(([id, title, text]) => {
              const disabled = id === "ai" && !aiAvailable;
              return (
                <button key={id} type="button" role="radio" aria-checked={mode === id} disabled={disabled}
                        onClick={() => setMode(id)}
                        className={`rounded-md border p-3 text-left disabled:cursor-not-allowed disabled:opacity-60 ${mode === id
                          ? "border-green-700 bg-green-50" : "border-stone-300 hover:bg-stone-50"}`}>
                  <span className="block font-medium">{title}</span>
                  <span className="text-xs text-stone-600">
                    {disabled ? (!rights.ai ? "Réservé au droit « Utiliser l'assistant IA »."
                      : !online ? "Indisponible hors ligne." : `IA indisponible${status.data?.reason ? ` : ${status.data.reason}` : ""}.`) : text}
                  </span>
                </button>
              );
            })}
        </div>
        <Select label="Variété" value={form.variety} onChange={set("variety")} error={errors.variety}
                options={varieties.map((v) => ({ value: v.id, label: `${v.crop_name} · ${v.name}` }))} />
        <Field label={mode === "ai" ? "Nom (facultatif)" : "Nom du plan"} value={form.name} onChange={set("name")}
               error={errors.name} hint="ex. Tomate · P-01" />
        {mode === "ai" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="Parcelle" value={form.parcel} onChange={set("parcel")} error={errors.parcel}
                    options={props.parcels.map((p) => ({ value: p.id, label: `${p.code || p.name} · ${formatArea(p.area_m2)}` }))} />
            <Field label="Date de début" type="date" value={form.planned_start_date} onChange={set("planned_start_date")}
                   error={errors.planned_start_date} />
            <Field label="Surface allouée (m²)" inputMode="decimal" value={form.allocated_area_m2} onChange={set("allocated_area_m2")}
                   error={errors.allocated_area_m2} />
            <Field label="dont non plantable (m²)" inputMode="decimal" value={form.non_plantable_area_m2}
                   onChange={set("non_plantable_area_m2")} />
            <Field label="Objectifs (facultatif)" value={form.objectives} onChange={set("objectives")} />
            <Field label="Contraintes (facultatif)" value={form.constraints} onChange={set("constraints")} />
          </div>
        )}
        {error && <ErrorMessage>{error}</ErrorMessage>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={props.onClose}>Fermer</Button>
          <Button type="submit" disabled={busy || !online}>
            {busy ? (mode === "ai" ? "L'IA prépare le brouillon…" : "Création…") : mode === "ai" ? "Demander un brouillon" : "Créer le plan"}
          </Button>
        </div>
        {!online && <p className="text-xs text-stone-500">Hors ligne : la création d'un plan demande une connexion (Q7).</p>}
      </form>
    </div>
  );
}
