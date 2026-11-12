/**
 * Journal of the farm's transactions, with the detail of one transaction and its
 * workflow actions. A validated transaction is never edited: it is reversed (reverse
 * entry, mandatory reason) or corrected (reversal + new linked transaction), FR-076.
 */

import {
  type FinanceRights, formatDate, formatDateTime, label, LOCAL_STATE_LABELS, TRANSACTION_KIND_LABELS,
  transactionActions, transactionBadges, transactionDirection,
} from "@fms/shared";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { Campaign, FinanceCategory, Paginated, Revision, Transaction, TreasuryAccount } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { type LocalMeta, useLocalEntities, useSync } from "../../sync/SyncContext";
import { Button, Card, EmptyState, Field, Loading, LocalStatus, Select, useBusy } from "../../ui/components";
import { errorText, results, transactionAction, useRemote } from "./data";
import { Badge, Money, ReasonDialog } from "./ui";

type Row = Transaction & Partial<LocalMeta>;

interface Filters {
  kind: string;
  status: string;
  account: string;
  campaign: string;
  from: string;
  to: string;
}

const NO_FILTER: Filters = { kind: "", status: "", account: "", campaign: "", from: "", to: "" };

function matches(tx: Row, f: Filters): boolean {
  if (f.kind && tx.kind !== f.kind) return false;
  if (f.status === "local" ? !tx._local : f.status && (tx._local || tx.status !== f.status)) return false;
  if (f.account && !(tx.entries ?? []).some((e) => e.account === f.account)
      && (tx as unknown as { account?: string }).account !== f.account) return false;
  if (f.campaign && tx.campaign !== f.campaign) return false;
  if (f.from && tx.business_date < f.from) return false;
  if (f.to && tx.business_date > f.to) return false;
  return true;
}

/** Local view, plus (without finance.view) the user's own entries listed by the server. */
export function useJournal(api: ApiClient, farmId: string, rights: FinanceRights): { rows: Row[]; loading: boolean } {
  const local = useLocalEntities<Transaction>("finance.transaction");
  const remote = useRemote<Paginated<Transaction>>(
    api, rights.view ? null : `/farms/${farmId}/transactions/?page_size=200`, `fms.own-transactions.${farmId}`);
  const rows = useMemo(() => {
    const byId = new Map<string, Row>();
    for (const tx of results(remote.data)) byId.set(tx.id, tx);
    for (const tx of local.rows) byId.set(tx._id, { ...tx, id: tx._id });
    return [...byId.values()].sort((a, b) => b.business_date.localeCompare(a.business_date)
      || (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }, [local.rows, remote.data]);
  return { rows, loading: local.loading };
}

export function JournalView(props: {
  api: ApiClient;
  rights: FinanceRights;
  accounts: TreasuryAccount[];
  categories: FinanceCategory[];
  campaigns: Campaign[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  onNew?: () => void;
}): ReactNode {
  const { farmId } = useSync();
  const { rows, loading } = useJournal(props.api, farmId, props.rights);
  const [filters, setFilters] = useState<Filters>(NO_FILTER);
  const shown = rows.filter((tx) => matches(tx, filters));
  const selected = rows.find((tx) => tx.id === props.selected) ?? null;
  const accountName = (id: string | undefined) => props.accounts.find((a) => a.id === id)?.name ?? "Compte";
  const categoryName = (id: string | null | undefined) => props.categories.find((c) => c.id === id)?.name;
  const set = (key: keyof Filters) => (e: { target: { value: string } }) => setFilters({ ...filters, [key]: e.target.value });

  const accountsOf = (tx: Row): string => {
    const entries = tx.entries ?? [];
    if (tx.kind === "transfer" && entries.length === 2) {
      const from = entries.find((e) => e.amount.startsWith("-"));
      const to = entries.find((e) => !e.amount.startsWith("-"));
      return `${accountName(from?.account)} → ${accountName(to?.account)}`;
    }
    const own = (tx as unknown as { account?: string; to_account?: string });
    if (entries.length === 0 && own.account) {
      return own.to_account ? `${accountName(own.account)} → ${accountName(own.to_account)}` : accountName(own.account);
    }
    return entries.map((e) => accountName(e.account)).join(", ");
  };

  return (
    <div className="flex flex-col gap-4">
      <form role="search" aria-label="Filtrer le journal" onSubmit={(e) => e.preventDefault()}
            className="grid gap-3 rounded-lg border border-stone-200 bg-white p-3 sm:grid-cols-3 lg:grid-cols-6">
        <Select label="Type" value={filters.kind} onChange={set("kind")} placeholder="Tous"
                options={Object.entries(TRANSACTION_KIND_LABELS).map(([value, l]) => ({ value, label: l }))} />
        <Select label="Statut" value={filters.status} onChange={set("status")} placeholder="Tous"
                options={[{ value: "local", label: "Pas encore envoyée" }, { value: "submitted", label: "À valider" },
                          { value: "validated", label: "Validée" }, { value: "rejected", label: "Rejetée" },
                          { value: "reversed", label: "Annulée" }]} />
        <Select label="Compte" value={filters.account} onChange={set("account")} placeholder="Tous les comptes"
                options={props.accounts.map((a) => ({ value: a.id, label: a.name }))} />
        <Select label="Campagne" value={filters.campaign} onChange={set("campaign")} placeholder="Toutes"
                options={props.campaigns.map((c) => ({ value: c.id, label: c.name }))} />
        <Field label="Du" type="date" value={filters.from} onChange={set("from")} />
        <Field label="Au" type="date" value={filters.to} onChange={set("to")} />
      </form>

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_380px]">
        {loading ? <Loading /> : shown.length === 0 ? (
          <EmptyState action={props.onNew && <Button onClick={props.onNew}>Nouvelle opération</Button>}>
            {rows.length === 0 ? "Aucune opération." : "Aucune opération ne correspond aux filtres."}
          </EmptyState>
        ) : (
          <Card>
            <ul aria-label="Opérations" className="divide-y divide-stone-100">
              {shown.map((tx) => {
                const reversed = tx.status === "reversed";
                return (
                  <li key={tx.id}>
                    <button type="button" aria-pressed={tx.id === props.selected}
                            onClick={() => props.onSelect(tx.id === props.selected ? null : tx.id)}
                            className={`grid w-full grid-cols-[64px_1fr_auto] items-center gap-3 border-l-4 p-3 text-left
                                        text-sm hover:bg-stone-50 focus-visible:outline-2 focus-visible:outline-green-700
                                        ${tx.id === props.selected ? "border-green-700 bg-green-50" : "border-transparent"}`}>
                      <span className="text-xs text-stone-500">{formatDate(tx.business_date).replace(/ \d{4}$/, "")}</span>
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className={`font-medium ${reversed ? "text-stone-500 line-through" : ""}`}>
                          {tx.description || categoryName(tx.category) || label(TRANSACTION_KIND_LABELS, tx.kind)}
                        </span>
                        <span className="text-xs text-stone-500">
                          {[label(TRANSACTION_KIND_LABELS, tx.kind), accountsOf(tx), categoryName(tx.category)]
                            .filter(Boolean).join(" · ")}
                        </span>
                        <span className="flex flex-wrap gap-1">
                          {tx._local ? <LocalStatus status={tx._local} />
                            : transactionBadges(tx).map((b) => <Badge key={b.label} tone={b.tone}>{b.label}</Badge>)}
                        </span>
                      </span>
                      <Money amount={tx.amount} currency={tx.currency} direction={transactionDirection(tx)}
                             className={reversed ? "text-stone-400" : ""} />
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
        {selected && (
          <TransactionDetail key={selected.id} api={props.api} tx={selected} rights={props.rights}
                             accountsOf={accountsOf} categoryName={categoryName}
                             campaignName={(id) => props.campaigns.find((c) => c.id === id)?.name}
                             onClose={() => props.onSelect(null)} />
        )}
      </div>
    </div>
  );
}

type Dialog = null | "reject" | "reverse" | "correct";

function TransactionDetail(props: {
  api: ApiClient;
  tx: Row;
  rights: FinanceRights;
  accountsOf: (tx: Row) => string;
  categoryName: (id: string | null | undefined) => string | undefined;
  campaignName: (id: string | null | undefined) => string | undefined;
  onClose: () => void;
}): ReactNode {
  const { tx } = props;
  const { farmId, syncNow, online } = useSync();
  const { notify } = useNotifications();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const [revisions, setRevisions] = useState<Revision[] | null>(null);
  const actions = tx._local ? { validate: false, reject: false, reverse: false, correct: false }
    : transactionActions(tx, props.rights);
  const kindLabel = label(TRANSACTION_KIND_LABELS, tx.kind);

  useEffect(() => {
    if (tx._local || !props.rights.view) return;
    let active = true;
    props.api.request<Revision[]>("GET", `/farms/${farmId}/transactions/${tx.id}/revisions/`)
      .then((r) => active && setRevisions(r)).catch(() => undefined); // history is optional offline
    return () => {
      active = false;
    };
  }, [props.api, farmId, tx.id, tx._local, props.rights.view]);

  /** Online action, then a sync round so that the local journal shows the new state. */
  const act = (action: string, body: object | undefined, done: string) => run(async () => {
    setError(null);
    try {
      await transactionAction(props.api, farmId, tx.id, action, body, tx.version ?? tx._version);
      notify({ type: "success", farmId, text: done });
      setDialog(null);
      await syncNow();
    } catch (err) {
      setError(errorText(err));
    }
  });

  return (
    <aside aria-label={`Détail : ${tx.description || kindLabel}`}
           className="flex flex-col gap-3 rounded-lg border border-stone-200 bg-white p-4 shadow-sm lg:sticky lg:top-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <span className="flex flex-wrap items-center gap-1 text-xs text-stone-500">
            {kindLabel}
            {tx._local ? <LocalStatus status={tx._local} />
              : transactionBadges(tx).map((b) => <Badge key={b.label} tone={b.tone}>{b.label}</Badge>)}
          </span>
          <h3 className="text-lg font-semibold">{tx.description || props.categoryName(tx.category) || kindLabel}</h3>
          <Money amount={tx.amount} currency={tx.currency} direction={transactionDirection(tx)} className="text-xl" />
        </div>
        <Button variant="ghost" aria-label="Fermer le détail" onClick={props.onClose}>✕</Button>
      </div>

      {tx.possible_duplicate && tx.status === "submitted" && (
        <p role="note" className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
          <strong>Doublon possible.</strong> Une opération semblable (même compte, montant, date et catégorie) a été
          saisie récemment par quelqu'un d'autre ou sur un autre appareil. Vérifiez avant de valider.
        </p>
      )}
      {tx.status === "rejected" && tx.rejected_reason && (
        <p className="rounded-md bg-red-50 p-2 text-sm text-red-800">Rejetée : {tx.rejected_reason}</p>
      )}

      <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-stone-500">Date</dt><dd>{formatDate(tx.business_date)}</dd>
        <dt className="text-stone-500">Compte</dt><dd>{props.accountsOf(tx)}</dd>
        {props.categoryName(tx.category) && (<><dt className="text-stone-500">Catégorie</dt>
          <dd>{props.categoryName(tx.category)}</dd></>)}
        {props.campaignName(tx.campaign) && (<><dt className="text-stone-500">Campagne</dt>
          <dd>{props.campaignName(tx.campaign)}</dd></>)}
        {tx.created_at && (<><dt className="text-stone-500">Saisie</dt>
          <dd>{formatDateTime(tx.created_at)}{tx.created_offline ? " (hors ligne)" : ""}</dd></>)}
        {tx.validated_at && (<><dt className="text-stone-500">Validée</dt><dd>{formatDateTime(tx.validated_at)}</dd></>)}
        {tx.reverses && (<><dt className="text-stone-500">Annule</dt><dd>une opération antérieure</dd></>)}
        {tx.corrects && (<><dt className="text-stone-500">Corrige</dt><dd>une opération annulée</dd></>)}
      </dl>
      {tx._local && (
        <p className="text-sm text-stone-600">
          {LOCAL_STATE_LABELS[tx._local]}. Les actions de validation seront possibles une fois l'opération reçue
          par le serveur.
        </p>
      )}

      {revisions && revisions.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm font-medium">Historique ({revisions.length + 1} versions)</summary>
          <ol className="mt-2 flex list-decimal flex-col gap-1 pl-5 text-sm text-stone-700">
            {revisions.map((r) => (
              <li key={r.revision}>
                {formatDateTime(r.changed_at)} · avant modification : {String(r.snapshot.amount ?? "")} {tx.currency}
                {r.reason ? ` (motif : « ${r.reason} »)` : ""}
              </li>
            ))}
          </ol>
        </details>
      )}

      {(actions.validate || actions.reverse) && (
        <div className="flex flex-col gap-2 border-t border-stone-200 pt-3">
          {error && !dialog && <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-800">{error}</p>}
          <div className="flex flex-wrap gap-2">
            {actions.validate && (
              <Button disabled={busy || !online}
                      onClick={() => void act("validate", undefined, `Opération validée : ${kindLabel.toLowerCase()}.`)}>
                Valider
              </Button>
            )}
            {actions.reject && <Button variant="secondary" disabled={!online} onClick={() => setDialog("reject")}>Rejeter…</Button>}
            {actions.correct && <Button variant="secondary" disabled={!online} onClick={() => setDialog("correct")}>Corriger…</Button>}
            {actions.reverse && (
              <Button variant="secondary" disabled={!online} className="text-red-700"
                      onClick={() => setDialog("reverse")}>Annuler l'opération…</Button>
            )}
          </div>
          <p className="text-xs text-stone-500">
            {online ? "Une opération validée n'est jamais modifiée ni supprimée : « Annuler » passe une écriture inverse, « Corriger » annule puis crée une opération liée."
              : "Hors ligne : la validation, le rejet et l'annulation demandent une connexion."}
          </p>
        </div>
      )}

      <ReasonDialog open={dialog === "reject"} title="Rejeter cette opération ?" busy={busy} error={error}
                    description="Le motif sera visible par l'auteur de la saisie." confirmLabel="Rejeter"
                    onCancel={() => setDialog(null)}
                    onConfirm={(reason) => void act("reject", { reason }, `Opération rejetée : ${kindLabel.toLowerCase()}.`)} />
      <ReasonDialog open={dialog === "reverse"} title="Annuler cette opération ?" busy={busy} error={error}
                    confirmLabel="Annuler l'opération" onCancel={() => setDialog(null)}
                    description="Une écriture inverse du même montant sera passée. L'opération d'origine reste visible dans le journal, marquée « Annulée »."
                    onConfirm={(reason) => void act("reverse", { reason }, "Opération annulée par une écriture inverse.")} />
      {dialog === "correct" && (
        <CorrectionDialog tx={tx} busy={busy} error={error} onCancel={() => setDialog(null)}
                          onConfirm={(body) => void act("correct", body, "Opération corrigée.")} />
      )}
    </aside>
  );
}

function CorrectionDialog(props: { tx: Row; busy: boolean; error: string | null;
                                   onConfirm: (body: Record<string, string>) => void; onCancel: () => void }): ReactNode {
  const [amount, setAmount] = useState(props.tx.amount.replace(/\.?0+$/, ""));
  const [date, setDate] = useState(props.tx.business_date);
  const [description, setDescription] = useState(props.tx.description);
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const confirm = () => {
    if (!reason.trim()) {
      setMissing(true);
      return;
    }
    props.onConfirm({ reason: reason.trim(), amount: amount.replace(",", ".").replace(/\s/g, ""),
                      business_date: date, description });
  };
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div role="dialog" aria-modal="true" aria-label="Corriger l'opération"
           className="flex w-full max-w-md flex-col gap-3 rounded-lg bg-white p-4 shadow-lg">
        <h2 className="font-semibold">Corriger l'opération</h2>
        <p className="text-sm text-stone-700">
          L'opération actuelle sera annulée et remplacée par une nouvelle, liée à elle. Les deux restent dans le journal.
        </p>
        <Field label={`Montant (${props.tx.currency})`} inputMode="decimal" value={amount}
               onChange={(e) => setAmount(e.target.value)} />
        <Field label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <Field label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        <Field label="Motif (obligatoire)" value={reason} onChange={(e) => setReason(e.target.value)}
               error={missing ? "Indiquez le motif." : undefined} />
        {props.error && <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-800">{props.error}</p>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={props.onCancel}>Retour</Button>
          <Button disabled={props.busy} onClick={confirm}>{props.busy ? "Envoi…" : "Corriger"}</Button>
        </div>
      </div>
    </div>
  );
}
