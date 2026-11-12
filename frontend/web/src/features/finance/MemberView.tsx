/**
 * The user's own member account (Q35): contributions with their proof, validated by the
 * farm manager, then transferred to the farm's main account within the validated balance.
 * A contributor sees nothing else of the farm's finances.
 */

import { formatDate, formatMoney, label, toAmount, TRANSACTION_KIND_LABELS, transactionBadges } from "@fms/shared";
import { type ReactNode, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { FinanceCategory, MemberStatement, Paginated, TreasuryAccount } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Button, Card, EmptyState, ErrorMessage, Loading, LocalStatus, useBusy } from "../../ui/components";
import type { FinanceRights } from "@fms/shared";
import { errorText, results, useRemote } from "./data";
import { useJournal } from "./JournalView";
import { TransactionForm } from "./TransactionForm";
import { Badge, Freshness, Money } from "./ui";

export function MemberView(props: { api: ApiClient; rights: FinanceRights; userId: string;
                                    categories: FinanceCategory[] }): ReactNode {
  const { farmId } = useSync();
  const { notify } = useNotifications();
  const [entry, setEntry] = useState<null | "funding" | "transfer">(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const accounts = useRemote<Paginated<TreasuryAccount>>(props.api, `/farms/${farmId}/treasury-accounts/?page_size=200`,
                                                         `fms.my-accounts.${farmId}`);
  const statements = useRemote<MemberStatement[]>(props.api, `/farms/${farmId}/treasury-accounts/members/`,
                                                  `fms.my-statement.${farmId}`);
  const journal = useJournal(props.api, farmId, props.rights);
  const mine = results(accounts.data).find((a) => a.role === "member" && a.holder === props.userId);
  const statement = (statements.data ?? []).find((s) => s.account === mine?.id);
  const movements = journal.rows.filter((tx) => mine && ((tx.entries ?? []).some((e) => e.account === mine.id)
    || (tx as unknown as { account?: string }).account === mine.id));

  const open = () => run(async () => {
    setError(null);
    try {
      await props.api.request("POST", `/farms/${farmId}/treasury-accounts/mine/`, {});
      notify({ type: "success", farmId, text: "Votre compte de membre est ouvert." });
      accounts.reload();
      statements.reload();
    } catch (err) {
      setError(errorText(err));
    }
  });

  if (accounts.loading && !accounts.data) return <Loading />;
  if (!mine) {
    return (
      <div className="flex flex-col gap-3">
        <Freshness offline={accounts.offline} error={accounts.error} fetchedAt={accounts.fetchedAt} onRetry={accounts.reload} />
        {error && <ErrorMessage>{error}</ErrorMessage>}
        <EmptyState hint="Il reçoit vos apports à l'exploitation, que vous transférez ensuite à sa trésorerie."
                    action={<Button disabled={busy} onClick={() => void open()}>Ouvrir mon compte de membre</Button>}>
          Vous n'avez pas encore de compte de membre.
        </EmptyState>
      </div>
    );
  }
  const balance = toAmount(statement?.balance);
  return (
    <div className="flex flex-col gap-4">
      <Freshness offline={statements.offline} error={statements.error} fetchedAt={statements.fetchedAt}
                 onRetry={statements.reload} />
      <Card className="flex flex-col gap-3 p-4">
        <div>
          <p className="text-sm text-stone-500">{mine.name} · solde disponible</p>
          <p className="text-2xl font-semibold tabular-nums">{formatMoney(balance, mine.currency)}</p>
        </div>
        <dl className="grid grid-cols-3 gap-3 border-t border-stone-100 pt-3 text-sm">
          <div><dt className="text-xs text-stone-500">Apporté (validé)</dt>
            <dd className="font-semibold tabular-nums">{formatMoney(toAmount(statement?.contributed), mine.currency)}</dd></div>
          <div><dt className="text-xs text-stone-500">En attente de validation</dt>
            <dd className="font-semibold tabular-nums text-amber-900">{formatMoney(toAmount(statement?.pending_contributions), mine.currency)}</dd></div>
          <div><dt className="text-xs text-stone-500">Versé à la trésorerie</dt>
            <dd className="font-semibold tabular-nums">{formatMoney(toAmount(statement?.transferred_to_treasury), mine.currency)}</dd></div>
        </dl>
        {!entry && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setEntry("funding")}>Apporter des fonds</Button>
            <Button variant="secondary" onClick={() => setEntry("transfer")}>Transférer à la trésorerie</Button>
          </div>
        )}
      </Card>

      {entry && (
        <TransactionForm kinds={[entry]} accounts={[mine]} categories={props.categories} campaigns={[]} loans={[]}
                         balances={{ [mine.id]: balance }}
                         title={entry === "funding" ? "Apporter des fonds" : `Transférer à la trésorerie (jusqu'à ${formatMoney(balance, mine.currency)})`}
                         onDone={() => { setEntry(null); statements.reload(); }} onCancel={() => setEntry(null)} />
      )}

      <Card>
        <h3 className="border-b border-stone-200 p-3 font-semibold">Mes mouvements</h3>
        {movements.length === 0 ? <p className="p-3 text-sm text-stone-500">Aucun mouvement.</p> : (
          <ul className="divide-y divide-stone-100">
            {movements.map((tx) => (
              <li key={tx.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                <span className="flex flex-col">
                  <span className="font-medium">{tx.kind === "transfer" ? "Transfert vers la trésorerie" : label(TRANSACTION_KIND_LABELS, tx.kind)}</span>
                  <span className="text-xs text-stone-500">{formatDate(tx.business_date)}{tx.description ? ` · ${tx.description}` : ""}</span>
                  <span className="flex gap-1">{tx._local ? <LocalStatus status={tx._local} />
                    : transactionBadges(tx).map((b) => <Badge key={b.label} tone={b.tone}>{b.label}</Badge>)}</span>
                </span>
                <Money amount={tx.amount} currency={tx.currency} direction={tx.kind === "transfer" ? "out" : "in"} />
              </li>
            ))}
          </ul>
        )}
      </Card>
      {!props.rights.view && (
        <p className="text-center text-xs text-stone-500">
          Rôle « Membre contributeur » : vous ne voyez que votre propre compte, pas les autres finances de l'exploitation.
        </p>
      )}
    </div>
  );
}
