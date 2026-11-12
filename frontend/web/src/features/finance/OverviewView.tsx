/** Balances, treasury flows per period and transactions waiting for validation (FR-074, FR-077). */

import {
  ACCOUNT_KIND_LABELS, ACCOUNT_ROLE_LABELS, addAmounts, type FinanceRights, formatDate, formatMoney, isNegative,
  isZero, label, summarizeTreasury, todayIso, toAmount, TRANSACTION_KIND_LABELS, treasuryWindow,
} from "@fms/shared";
import { type ReactNode, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { AccountBalance, TreasuryAccount } from "../../api/types";
import { useSync } from "../../sync/SyncContext";
import { Button, Card, EmptyState, Loading } from "../../ui/components";
import { useRemote } from "./data";
import { useJournal } from "./JournalView";
import { Badge, Freshness, Money, Segmented, SignedMoney } from "./ui";

type Period = "day" | "week" | "month";
const PERIOD_HEAD: Record<Period, string> = { day: "Jour", week: "Semaine du", month: "Mois" };

function periodLabel(start: string, period: Period): string {
  const d = formatDate(start);
  return period === "month" ? d.replace(/^\d+ /, "") : d.replace(/ \d{4}$/, "");
}

const cell = (amount: string, currency: string) =>
  isZero(amount) ? <span className="text-stone-400">0</span> : formatMoney(amount, currency).replace(` ${currency}`, "");

export function OverviewView(props: { api: ApiClient; rights: FinanceRights; accounts: TreasuryAccount[];
                                      onExamine: (id: string) => void; onNew?: () => void }): ReactNode {
  const { farmId } = useSync();
  const [period, setPeriod] = useState<Period>("week");
  const range = treasuryWindow(todayIso(), period);
  const balances = useRemote<AccountBalance[]>(props.api, `/farms/${farmId}/treasury-accounts/balances/`,
                                               `fms.balances.${farmId}`);
  const report = useRemote<Parameters<typeof summarizeTreasury>[0]>(
    props.api, `/farms/${farmId}/transactions/treasury/?period=${period}&date_from=${range.from}&date_to=${range.to}`,
    `fms.treasury.${farmId}.${period}`);
  const journal = useJournal(props.api, farmId, props.rights);
  const pending = journal.rows.filter((tx) => !tx._local && tx.status === "submitted");
  const summaries = report.data ? summarizeTreasury(report.data) : [];

  const rows = (balances.data ?? []).filter((b) => b.is_active || !isZero(toAmount(b.balance)));
  const farmAccounts = rows.filter((b) => b.role !== "member");
  const members = rows.filter((b) => b.role === "member");
  const memberTotals = [...new Set(members.map((m) => m.currency))].map((currency) => ({
    currency, total: addAmounts(...members.filter((m) => m.currency === currency).map((m) => m.balance)) }));
  const kindOf = (id: string) => props.accounts.find((a) => a.id === id)?.kind;

  return (
    <div className="flex flex-col gap-4">
      <Freshness offline={balances.offline} error={balances.error} fetchedAt={balances.fetchedAt}
                 onRetry={() => { balances.reload(); report.reload(); }} />
      <section aria-label="Soldes" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {balances.loading && !balances.data ? <Loading /> : farmAccounts.length === 0 && !balances.data ? null : (
          farmAccounts.map((b) => (
            <Card key={b.account} className={`p-3 ${b.role === "main" ? "border-t-4 border-t-green-700" : ""}`}>
              <p className="text-xs text-stone-500">
                {b.name}{kindOf(b.account) ? ` · ${label(ACCOUNT_KIND_LABELS, kindOf(b.account))}` : ""}
              </p>
              <p className={`text-xl font-semibold tabular-nums ${isNegative(toAmount(b.balance)) ? "text-red-700" : ""}`}>
                <SignedMoney amount={toAmount(b.balance)} currency={b.currency} />
              </p>
              <p className="text-xs text-stone-500">
                {label(ACCOUNT_ROLE_LABELS, b.role)}
                {!isZero(toAmount(b.pending)) && <> · en attente : <SignedMoney amount={toAmount(b.pending)} currency={b.currency} /></>}
              </p>
            </Card>
          ))
        )}
        {memberTotals.map((m) => (
          <Card key={m.currency} className="bg-stone-50 p-3">
            <p className="text-xs text-stone-500">Comptes de membres ({members.filter((x) => x.currency === m.currency).length})</p>
            <p className="text-xl font-semibold tabular-nums">{formatMoney(m.total, m.currency)}</p>
            <p className="text-xs text-stone-500">Pas encore transférés à la trésorerie</p>
          </Card>
        ))}
      </section>
      {balances.data && (
        <p className="-mt-2 text-xs text-stone-500">
          Soldes calculés sur les opérations validées. Les opérations soumises ou en attente d'envoi n'y figurent pas.
        </p>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2 p-3 pb-1">
            <h3 className="font-semibold">
              Trésorerie · {formatDate(range.from)} → {formatDate(range.to)}
            </h3>
            <Segmented label="Regrouper par" value={period} onChange={setPeriod}
                       options={[{ id: "day", label: "Jour" }, { id: "week", label: "Semaine" }, { id: "month", label: "Mois" }]} />
          </div>
          {report.loading && !report.data ? <Loading /> : summaries.length === 0 ? (
            <div className="p-3"><EmptyState>{report.error ? "Rapport indisponible hors ligne." : "Aucun mouvement validé."}</EmptyState></div>
          ) : summaries.map((s) => (
            <div key={s.currency} className="flex flex-col gap-2 p-1">
              <div className="overflow-x-auto">
                <table className="w-full text-sm tabular-nums">
                  <caption className="sr-only">Flux de trésorerie en {s.currency}</caption>
                  <thead>
                    <tr className="border-b border-stone-200 text-xs text-stone-500">
                      <th scope="col" className="p-2 text-left">{PERIOD_HEAD[period]}</th>
                      <th scope="col" className="p-2 text-right">Recettes</th>
                      <th scope="col" className="p-2 text-right">Dépenses de campagne</th>
                      <th scope="col" className="p-2 text-right">Investissements</th>
                      <th scope="col" className="p-2 text-right">Apports et prêts</th>
                      <th scope="col" className="p-2 text-right">Remboursements</th>
                      <th scope="col" className="p-2 text-right">Solde de fin</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-stone-100">
                      <td className="p-2 text-stone-500">Solde d'ouverture</td><td /><td /><td /><td /><td />
                      <td className="p-2 text-right"><SignedMoney amount={s.opening} currency={s.currency} /></td>
                    </tr>
                    {s.periods.map((p) => (
                      <tr key={p.period_start} className="border-b border-stone-100">
                        <td className="p-2">{periodLabel(p.period_start, period)}</td>
                        <td className="p-2 text-right">{cell(p.inflows, s.currency)}</td>
                        <td className="p-2 text-right">{cell(p.outflows, s.currency)}</td>
                        <td className="p-2 text-right">{cell(p.investments, s.currency)}</td>
                        <td className="p-2 text-right">{cell(p.fundings, s.currency)}</td>
                        <td className="p-2 text-right">{cell(p.repayments, s.currency)}</td>
                        <td className="p-2 text-right"><SignedMoney amount={p.closing_balance} currency={s.currency} /></td>
                      </tr>
                    ))}
                    <tr className="bg-stone-50 font-semibold">
                      <td className="p-2">Total ({s.currency})</td>
                      <td className="p-2 text-right text-green-800">{cell(s.totals.inflows, s.currency)}</td>
                      <td className="p-2 text-right text-red-700">{cell(s.totals.outflows, s.currency)}</td>
                      <td className="p-2 text-right">{cell(s.totals.investments, s.currency)}</td>
                      <td className="p-2 text-right">{cell(s.totals.fundings, s.currency)}</td>
                      <td className="p-2 text-right">{cell(s.totals.repayments, s.currency)}</td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="flex flex-col gap-1 px-2 pb-2 text-sm">
                <p>
                  Résultat de campagne sur la période :{" "}
                  <strong className={isNegative(s.campaignResult) ? "text-red-700" : "text-green-800"}>
                    <SignedMoney amount={s.campaignResult} currency={s.currency} />
                  </strong>{" "}
                  <span className="text-xs text-stone-500">(recettes − dépenses de campagne)</span>
                </p>
                <p className="text-xs text-stone-500">
                  Les apports, les prêts, leurs remboursements et les investissements ne comptent ni en recette ni en
                  dépense de campagne. Les transferts entre comptes ({formatMoney(s.totals.transfers, s.currency)} sur
                  la période) n'apparaissent pas dans les totaux.
                </p>
              </div>
            </div>
          ))}
        </Card>

        <Card>
          <div className="flex items-center justify-between border-b border-stone-200 p-3">
            <h3 className="font-semibold">À valider ({pending.length})</h3>
          </div>
          {pending.length === 0 ? (
            <p className="p-3 text-sm text-stone-500">Rien à valider.</p>
          ) : (
            <ul className="divide-y divide-stone-100">
              {pending.slice(0, 6).map((tx) => (
                <li key={tx.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <span className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium">
                      {tx.description || label(TRANSACTION_KIND_LABELS, tx.kind)} ·{" "}
                      <Money amount={tx.amount} currency={tx.currency} />
                    </span>
                    <span className="text-xs text-stone-500">
                      {label(TRANSACTION_KIND_LABELS, tx.kind)} · {formatDate(tx.business_date)}
                    </span>
                    {tx.possible_duplicate && <span><Badge tone="pending">Doublon possible</Badge></span>}
                  </span>
                  <Button variant="secondary" onClick={() => props.onExamine(tx.id)}>Examiner</Button>
                </li>
              ))}
            </ul>
          )}
          {props.onNew && pending.length === 0 && (
            <div className="p-3 pt-0"><Button variant="ghost" onClick={props.onNew}>Nouvelle opération</Button></div>
          )}
        </Card>
      </div>
    </div>
  );
}
