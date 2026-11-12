/** Planned vs actual per budget line of a campaign (FR-075): actual = validated allocations only. */

import {
  amountError, budgetTotals, consumption, type FinanceRights, formatMoney, formatPercent, isNegative,
  normalizeBudgetRows, parseAmount, amountToString,
} from "@fms/shared";
import { type FormEvent, type ReactNode, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { Campaign, FinanceCategory } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Button, Card, EmptyState, ErrorMessage, Field, Loading, Select, useBusy } from "../../ui/components";
import { errorText, useRemote } from "./data";
import { Badge, Freshness, SignedMoney } from "./ui";

const variance = (amount: string, currency: string) => (
  <span className={isNegative(amount) ? "text-green-800" : amount === "0" ? "" : "font-semibold text-red-700"}>
    {amount !== "0" && !isNegative(amount) ? "+" : ""}<SignedMoney amount={amount} currency={currency} />
  </span>
);

export function BudgetView(props: { api: ApiClient; rights: FinanceRights; campaigns: Campaign[];
                                    categories: FinanceCategory[]; currency: string }): ReactNode {
  const { farmId } = useSync();
  const current = props.campaigns.find((c) => c.status === "active") ?? props.campaigns[0];
  const [campaign, setCampaign] = useState(current?.id ?? "");
  const [adding, setAdding] = useState(false);
  const report = useRemote<Record<string, string | number | null>[]>(
    props.api, campaign ? `/farms/${farmId}/budget-lines/report/?campaign=${campaign}` : null,
    `fms.budget.${farmId}.${campaign}`);
  const rows = normalizeBudgetRows(report.data ?? []);
  const totals = budgetTotals(rows);

  if (props.campaigns.length === 0) {
    return <EmptyState hint="Les budgets se rattachent à une campagne, créée dans l'onglet Campagnes.">Aucune campagne.</EmptyState>;
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-72">
          <Select label="Campagne" value={campaign} onChange={(e) => setCampaign(e.target.value)} placeholder="Choisir…"
                  options={props.campaigns.map((c) => ({ value: c.id, label: c.name }))} />
        </div>
        {props.rights.editBudget && campaign && !adding && (
          <Button onClick={() => setAdding(true)}>Ajouter une ligne</Button>
        )}
      </div>
      <Freshness offline={report.offline} error={report.error} fetchedAt={report.fetchedAt} onRetry={report.reload} />

      {totals.map((t) => (
        <section key={t.currency} aria-label={`Synthèse du budget (${t.currency})`} className="grid gap-3 sm:grid-cols-4">
          <Card className="p-3"><p className="text-xs text-stone-500">Budget prévu</p>
            <p className="text-xl font-semibold tabular-nums">{formatMoney(t.planned, t.currency)}</p></Card>
          <Card className="p-3"><p className="text-xs text-stone-500">Réalisé (validé)</p>
            <p className="text-xl font-semibold tabular-nums">{formatMoney(t.actual, t.currency)}</p></Card>
          <Card className="p-3"><p className="text-xs text-stone-500">En attente de validation</p>
            <p className="text-xl font-semibold tabular-nums text-amber-900">{formatMoney(t.pending, t.currency)}</p></Card>
          <Card className="p-3"><p className="text-xs text-stone-500">Écart</p>
            <p className="text-xl font-semibold tabular-nums">{variance(t.variance, t.currency)}</p>
            <p className="text-xs text-stone-500">{formatPercent(t.variance_pct)}</p></Card>
        </section>
      ))}

      {adding && (
        <BudgetLineForm api={props.api} campaign={campaign} currency={props.currency} categories={props.categories}
                        onDone={() => { setAdding(false); report.reload(); }} onCancel={() => setAdding(false)} />
      )}

      {report.loading && !report.data ? <Loading /> : rows.length === 0 ? (
        <EmptyState>{report.error ? "Budget indisponible hors ligne." : "Aucune ligne de budget pour cette campagne."}</EmptyState>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <caption className="sr-only">Lignes de budget</caption>
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th scope="col" className="p-2 text-left">Ligne</th>
                  <th scope="col" className="p-2 text-right">Prévu</th>
                  <th scope="col" className="p-2 text-right">Réalisé</th>
                  <th scope="col" className="p-2 text-right">En attente</th>
                  <th scope="col" className="p-2 text-right">Écart</th>
                  <th scope="col" className="p-2 text-right">Écart %</th>
                  <th scope="col" className="p-2"><span className="sr-only">Consommation</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const c = consumption(r);
                  return (
                    <tr key={r.budget_line} className="border-b border-stone-100">
                      <td className="p-2"><span className="font-medium">{r.label}</span><br />
                        <span className="text-xs text-stone-500">{r.category}</span></td>
                      <td className="p-2 text-right">{formatMoney(r.planned, r.currency)}</td>
                      <td className="p-2 text-right">{formatMoney(r.actual, r.currency)}</td>
                      <td className="p-2 text-right text-amber-900">{formatMoney(r.pending, r.currency)}</td>
                      <td className="p-2 text-right">{variance(r.variance, r.currency)}</td>
                      <td className="p-2 text-right">{formatPercent(r.variance_pct)}</td>
                      <td className="p-2">
                        <div className="relative h-2 w-32 overflow-hidden rounded-full bg-stone-100"
                             role="img" aria-label={`${Math.round(c.actual)} % consommé`}>
                          <span className={`absolute inset-y-0 left-0 ${c.over ? "bg-red-600" : "bg-green-700"}`}
                                style={{ width: `${c.actual}%` }} />
                          <span className="absolute inset-y-0 bg-amber-300" style={{ left: `${c.actual}%`, width: `${c.pending}%` }} />
                        </div>
                        {c.over && <span className="mt-1 inline-block"><Badge tone="danger">Dépassement</Badge></span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="p-3 text-xs text-stone-500">
            Réalisé : dépenses validées rattachées explicitement à la ligne. Écart = réalisé − prévu ; les montants
            en attente n'y comptent pas. Barre : vert pour le réalisé, jaune pour l'attente, rouge au-delà du prévu.
          </p>
        </Card>
      )}
    </div>
  );
}

function BudgetLineForm(props: { api: ApiClient; campaign: string; currency: string; categories: FinanceCategory[];
                                 onDone: () => void; onCancel: () => void }): ReactNode {
  const { farmId } = useSync();
  const { notify } = useNotifications();
  const [form, setForm] = useState({ label: "", category: "", planned: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof typeof form, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const found: typeof errors = {};
      if (!form.label.trim()) found.label = "Libellé obligatoire.";
      if (!form.category) found.category = "Catégorie obligatoire.";
      const amount = amountError(form.planned, props.currency);
      if (amount && parseAmount(form.planned) !== 0n) found.planned = amount;
      setErrors(found);
      if (Object.values(found).some(Boolean)) return;
      try {
        await props.api.request("POST", `/farms/${farmId}/budget-lines/`, {
          campaign: props.campaign, category: form.category, label: form.label.trim(), currency: props.currency,
          planned_amount: amountToString(parseAmount(form.planned) ?? 0n) });
        notify({ type: "success", farmId, text: `Ligne de budget « ${form.label.trim()} » ajoutée.` });
        props.onDone();
      } catch (err) {
        setError(errorText(err));
      }
    });
  };
  return (
    <Card>
      <form onSubmit={submit} noValidate aria-label="Nouvelle ligne de budget" className="grid gap-3 p-4 sm:grid-cols-3">
        <h3 className="font-medium sm:col-span-3">Nouvelle ligne de budget</h3>
        <Field label="Libellé" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}
               error={errors.label} />
        <Select label="Catégorie" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
                error={errors.category}
                options={props.categories.filter((c) => c.kind === "expense").map((c) => ({ value: c.id, label: c.name }))} />
        <Field label={`Montant prévu (${props.currency})`} inputMode="decimal" value={form.planned}
               onChange={(e) => setForm({ ...form, planned: e.target.value })} error={errors.planned} />
        {error && <div className="sm:col-span-3"><ErrorMessage>{error}</ErrorMessage></div>}
        <div className="flex gap-2 sm:col-span-3">
          <Button type="submit" disabled={busy}>{busy ? "Enregistrement…" : "Ajouter la ligne"}</Button>
          <Button variant="secondary" onClick={props.onCancel}>Annuler</Button>
        </div>
      </form>
    </Card>
  );
}
