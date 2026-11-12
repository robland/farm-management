/**
 * A validated (frozen) version: the engine's results with their traceability, the
 * calendar and its tasks, the versions and their comparison (FR-034), task generation.
 */

import {
  comparisonRows, engineNumber, formatArea, formatDate, formatDateTime, label, output, PHASE_LABELS, planRights,
  plantGap, resultsByParcel, TASK_STATUS_LABELS, todayIso, VERSION_ORIGIN_LABELS, VERSION_STATUS_LABELS, versionActions,
  type CalculationLike,
} from "@fms/shared";
import { type ReactNode, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { MeFarm, PlanVersion, ProductionPlan } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Badge, Segmented } from "../../ui/controls";
import { Button, Card, EmptyState, ErrorMessage, Field, Select, useBusy } from "../../ui/components";
import { errorText, type Planning } from "./data";

type Tab = "results" | "calendar" | "versions";
type Summary = { created: number; unchanged: number; replanned: number; cancelled: number; kept: number };

function Metric(props: { label: string; value: string; hint?: string }): ReactNode {
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <p className="text-xs text-stone-500">{props.label}</p>
      <p className="text-lg font-semibold tabular-nums">{props.value}</p>
      {props.hint && <p className="text-xs text-stone-500">{props.hint}</p>}
    </div>
  );
}

function Trace({ calc, title }: { calc: CalculationLike; title: string }): ReactNode {
  return (
    <details className="rounded-lg border border-stone-200 bg-white p-3">
      <summary className="cursor-pointer text-sm font-semibold">Traçabilité : {title}</summary>
      <div className="mt-2 grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <p className="text-xs font-semibold text-stone-500">Entrées et unités</p>
          <ul className="mt-1 list-disc pl-5">
            {Object.entries(calc.inputs).map(([name, q]) => (
              <li key={name}>{name} : {String(q.value ?? "—")}{q.unit ? ` ${q.unit}` : ""}</li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-2">
          <div><p className="text-xs font-semibold text-stone-500">Formule</p>
            <code className="block rounded bg-stone-100 p-2 text-xs whitespace-pre-wrap">{calc.formula}</code></div>
          {calc.assumptions.length > 0 && (
            <div><p className="text-xs font-semibold text-stone-500">Hypothèses</p>
              <ul className="list-disc pl-5">{calc.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>
          )}
          <div><p className="text-xs font-semibold text-stone-500">Alertes</p>
            {calc.warnings.length ? <ul className="list-disc pl-5 text-amber-900">{calc.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              : <p>Aucune.</p>}</div>
          <p className="text-xs text-stone-500">Moteur {calc.engine_version ?? ""}{calc.created_at ? ` · calcul du ${formatDateTime(calc.created_at)}` : ""}</p>
        </div>
      </div>
    </details>
  );
}

export function PlanDetail(props: { api: ApiClient; farm: MeFarm; plan: ProductionPlan; version: PlanVersion;
                                    planning: Planning; onChange: (v: PlanVersion) => void }): ReactNode {
  const { farmId, online, syncNow } = useSync();
  const { notify } = useNotifications();
  const rights = planRights(props.farm.permissions);
  const { version, plan } = props;
  const versions = props.planning.versions.filter((v) => v.plan === plan.id).sort((a, b) => b.number - a.number);
  const actions = versionActions(version, rights, { complete: true, pendingSuggestions: 0,
    hasDraft: versions.some((v) => v.status === "draft"), planClosed: ["closed", "cancelled"].includes(plan.status) });
  const [tab, setTab] = useState<Tab>("results");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [newVersion, setNewVersion] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const parcelName = (id: string) => {
    const p = props.planning.parcels.find((x) => x.id === id);
    return p ? p.code || p.name : "Parcelle";
  };

  const generate = () => void run(async () => {
    setError(null);
    try {
      setSummary(await props.api.request<Summary>("POST", `/farms/${farmId}/tasks/generate/`, { plan_version: version.id }));
      await syncNow();
    } catch (err) {
      setError(errorText(err));
    }
  });
  const createVersion = () => void run(async () => {
    setError(null);
    try {
      const draft = await props.api.request<PlanVersion>("POST", `/farms/${farmId}/plans/${plan.id}/new-version/`,
                                                         { based_on: version.id, change_note: note.trim() });
      notify({ type: "success", farmId, text: `Version ${draft.number} créée en brouillon : la version ${version.number} reste intacte.` });
      setNewVersion(false);
      props.onChange(draft);
    } catch (err) {
      setError(errorText(err));
    }
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-stone-600">
          {version.status === "validated" ? `Validée le ${version.validated_at ? formatDateTime(version.validated_at) : "—"} · figée : toute évolution passe par une nouvelle version.`
            : version.status === "draft" ? "Brouillon en préparation (lecture seule pour vous)." : label(VERSION_STATUS_LABELS, version.status)}
        </p>
        <div className="flex gap-2">
          {actions.newVersion && <Button variant="secondary" disabled={!online} onClick={() => setNewVersion(true)}>Nouvelle version</Button>}
          {actions.generateTasks && <Button disabled={busy || !online} onClick={generate}>Générer les tâches</Button>}
        </div>
      </div>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {newVersion && (
        <Card className="flex flex-col gap-3 p-4">
          <h3 className="font-semibold">Nouvelle version (copie de la version {version.number})</h3>
          <Field label="Note de changement (facultatif)" value={note} onChange={(e) => setNote(e.target.value)}
                 hint="ex. Pépinière allongée, écartement réduit" />
          <div className="flex gap-2">
            <Button disabled={busy} onClick={createVersion}>Créer le brouillon</Button>
            <Button variant="secondary" onClick={() => setNewVersion(false)}>Annuler</Button>
          </div>
        </Card>
      )}
      {summary && (
        <Card className="flex flex-col gap-2 p-4" >
          <h3 className="font-semibold" role="status">Tâches mises à jour depuis la version {version.number}</h3>
          <ul className="grid gap-1 text-sm sm:grid-cols-5">
            <li>Créées : <strong>{summary.created}</strong></li>
            <li>Conservées (commencées ou terminées) : <strong>{summary.kept}</strong></li>
            <li>Replanifiées : <strong>{summary.replanned}</strong></li>
            <li>Inchangées : <strong>{summary.unchanged}</strong></li>
            <li>Retirées du plan : <strong>{summary.cancelled}</strong></li>
          </ul>
          <p className="text-xs text-stone-500">La génération peut être relancée sans créer de doublons ; l'historique réalisé n'est jamais réécrit.</p>
          <div><Button variant="ghost" onClick={() => setSummary(null)}>Fermer</Button></div>
        </Card>
      )}

      <Segmented label="Plan" value={tab} onChange={setTab}
                 options={[{ id: "results", label: "Résultats" }, { id: "calendar", label: "Calendrier" },
                           { id: "versions", label: `Versions (${versions.length})` }]} />
      {tab === "results" && <Results version={version} parcelName={parcelName} />}
      {tab === "calendar" && <Calendar version={version} plan={plan} planning={props.planning} />}
      {tab === "versions" && <Versions api={props.api} plan={plan} versions={versions} parcelName={parcelName} />}
    </div>
  );
}

function Results({ version, parcelName }: { version: PlanVersion; parcelName: (id: string) => string }): ReactNode {
  const byParcel = resultsByParcel(version.calculations);
  const harvest = version.phases.find((p) => p.phase_code === "harvest");
  if (version.allocations.length === 0) return <EmptyState>Aucune parcelle dans cette version.</EmptyState>;
  return (
    <div className="flex flex-col gap-4">
      {version.allocations.map((a) => {
        const r = byParcel[a.parcel] ?? {};
        const gap = plantGap(r.density);
        return (
          <section key={a.parcel} aria-label={`Résultats ${parcelName(a.parcel)}`} className="flex flex-col gap-3">
            <h3 className="font-semibold">
              {parcelName(a.parcel)} · {formatArea(a.allocated_area_m2)} alloués, dont {formatArea(a.non_plantable_area_m2)} non plantables
            </h3>
            {!r.density ? <p className="text-sm text-stone-500">Pas encore calculé.</p> : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label="Surface plantable" value={formatArea(output(r.density, "plantable_area_m2") ?? "0")} />
                <Metric label="Densité théorique" value={`${engineNumber(output(r.density, "theoretical_density_per_m2"))} plants/m²`}
                        hint={`${engineNumber(output(r.density, "theoretical_density_per_ha"), 0)} plants/ha`} />
                <Metric label="Densité réelle (surface brute)" value={`${engineNumber(output(r.density, "real_density_per_m2"))} plants/m²`}
                        hint={`${engineNumber(output(r.density, "real_density_per_ha"), 0)} plants/ha · ${engineNumber(output(r.density, "real_density_on_plantable_per_m2"))} /m² plantable`} />
                <Metric label="Nombre de plants" value={engineNumber(output(r.density, "plant_count"), 0)}
                        hint={`théorique : ${engineNumber(output(r.density, "theoretical_plant_count"), 0)}${gap ? ` (${gap})` : ""}`} />
                {r.seeds && (
                  <>
                    <Metric label="Graines nécessaires" value={engineNumber(output(r.seeds, "seed_count"), 0)} hint="marge et taux compris" />
                    <Metric label="Masse de semences" value={`${engineNumber(output(r.seeds, "seed_mass_g"))} g`} />
                    {output(r.seeds, "packages") && <Metric label="Sachets" value={engineNumber(output(r.seeds, "packages"), 0)} />}
                  </>
                )}
                {harvest?.start_date && harvest.end_date && (
                  <Metric label="Récolte prévue" value={`${formatDate(harvest.start_date)} → ${formatDate(harvest.end_date)}`} />
                )}
              </div>
            )}
            {r.density && <Trace calc={r.density} title="densité et nombre de plants" />}
            {r.seeds && <Trace calc={r.seeds} title="besoin en semences" />}
          </section>
        );
      })}
    </div>
  );
}

function Calendar({ version, plan, planning }: { version: PlanVersion; plan: ProductionPlan; planning: Planning }): ReactNode {
  const tasks = planning.tasks.filter((t) => t.plan === plan.id && t.status !== "cancelled");
  const today = todayIso();
  const phases = [...version.phases].sort((a, b) => a.sequence - b.sequence);
  return (
    <Card>
      <table className="w-full text-sm">
        <caption className="sr-only">Calendrier cultural</caption>
        <thead>
          <tr className="border-b border-stone-200 text-left text-xs text-stone-500">
            <th className="p-2">Phase</th><th className="p-2">Dates</th><th className="p-2">Durée</th><th className="p-2">Tâches</th>
          </tr>
        </thead>
        <tbody>
          {phases.map((p) => {
            const own = tasks.filter((t) => p.start_date && t.planned_start_date === p.start_date);
            const current = p.start_date && p.end_date && p.start_date <= today && today <= p.end_date;
            return (
              <tr key={p.phase_code} className={`border-b border-stone-100 ${current ? "bg-green-50" : ""}`}>
                <td className="p-2">{PHASE_LABELS[p.phase_code] ?? p.phase_code}{current ? <strong> · phase actuelle</strong> : null}</td>
                <td className="p-2">{p.start_date && p.end_date ? `${formatDate(p.start_date)} → ${formatDate(p.end_date)}` : "—"}</td>
                <td className="p-2">{p.duration_days ? `${p.duration_days} j` : "—"}</td>
                <td className="p-2">
                  {own.length === 0 ? <span className="text-stone-400">—</span> : own.map((t) => (
                    <Badge key={t.id} tone={t.status === "done" ? "ok" : t.status === "in_progress" ? "info" : "neutral"}>
                      {label(TASK_STATUS_LABELS, t.status)}
                    </Badge>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="p-3 text-xs text-stone-500">
        Ajuster une date passe par une nouvelle version. Les tâches commencées ou terminées ne sont jamais réécrites.
      </p>
    </Card>
  );
}

function Versions(props: { api: ApiClient; plan: ProductionPlan; versions: PlanVersion[]; parcelName: (id: string) => string }): ReactNode {
  const { farmId, online } = useSync();
  const [a, setA] = useState(props.versions[1]?.id ?? "");
  const [b, setB] = useState(props.versions[0]?.id ?? "");
  const [rows, setRows] = useState<ReturnType<typeof comparisonRows> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const compare = () => void run(async () => {
    setError(null);
    try {
      const result = await props.api.request<{ differences: { section: string; field: string; from: unknown; to: unknown }[] }>(
        "GET", `/farms/${farmId}/plans/${props.plan.id}/compare/?a=${a}&b=${b}`);
      setRows(comparisonRows(result.differences, props.parcelName));
    } catch (err) {
      setError(errorText(err));
    }
  });
  const name = (id: string) => `Version ${props.versions.find((v) => v.id === id)?.number ?? "?"}`;
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[280px_1fr]">
      <Card className="flex flex-col gap-1 p-2">
        {props.versions.map((v) => (
          <div key={v.id} className={`rounded-md p-2 ${v.status === "validated" ? "border border-green-200 bg-green-50" : ""}`}>
            <p className="font-semibold">Version {v.number} <Badge tone={v.status === "validated" ? "ok" : v.status === "draft" ? "neutral" : "muted"}>
              {label(VERSION_STATUS_LABELS, v.status)}</Badge></p>
            <p className="text-xs text-stone-500">{label(VERSION_ORIGIN_LABELS, v.origin)}{v.validated_at ? ` · validée le ${formatDate(v.validated_at.slice(0, 10))}` : ""}</p>
            {v.change_note && <p className="mt-1 text-sm">« {v.change_note} »</p>}
          </div>
        ))}
      </Card>
      <Card className="flex flex-col gap-3 p-3">
        {props.versions.length < 2 ? <p className="text-sm text-stone-500">Une seule version : rien à comparer.</p> : (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-40"><Select label="De" value={a} onChange={(e) => setA(e.target.value)}
                                            options={props.versions.map((v) => ({ value: v.id, label: name(v.id) }))} /></div>
              <div className="w-40"><Select label="À" value={b} onChange={(e) => setB(e.target.value)}
                                            options={props.versions.map((v) => ({ value: v.id, label: name(v.id) }))} /></div>
              <Button variant="secondary" disabled={busy || !online || !a || !b || a === b} onClick={compare}>Comparer</Button>
            </div>
            {error && <ErrorMessage>{error}</ErrorMessage>}
            {rows && (rows.length === 0 ? <p className="text-sm text-stone-500">Aucune différence.</p> : (
              <table className="w-full text-sm">
                <caption className="sr-only">Différences entre {name(a)} et {name(b)}</caption>
                <thead><tr className="border-b border-stone-200 text-left text-xs text-stone-500">
                  <th className="p-2">Section</th><th className="p-2">Donnée</th><th className="p-2">{name(a)}</th><th className="p-2">{name(b)}</th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.section}-${r.field}`} className="border-b border-stone-100">
                      <td className="p-2">{r.section}</td><td className="p-2">{r.field}</td>
                      <td className="p-2 text-stone-400 line-through">{r.from}</td><td className="p-2 font-semibold text-green-800">{r.to}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
            <p className="text-xs text-stone-500">Seules les différences sont listées.</p>
          </>
        )}
      </Card>
    </div>
  );
}
