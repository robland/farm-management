/**
 * Finances tab: overview, journal, budgets, accounts and the user's member account. What
 * is shown depends on the permissions; the server enforces them (Q35).
 */

import {
  type EntryKind, FINANCE_VIEW_LABELS, type FinanceView, financeRights, financeViews, toAmount,
} from "@fms/shared";
import { type ReactNode, useMemo, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { AccountBalance, LoanPosition, MeFarm, TreasuryAccount } from "../../api/types";
import { useLocalEntities, useSync } from "../../sync/SyncContext";
import { Button, EmptyState } from "../../ui/components";
import { AccountsView } from "./AccountsView";
import { BudgetView } from "./BudgetView";
import { useCampaigns, useCategories, useRemote } from "./data";
import { JournalView } from "./JournalView";
import { MemberView } from "./MemberView";
import { OverviewView } from "./OverviewView";
import { TransactionForm } from "./TransactionForm";
import { SubNav } from "./ui";

const VIEW_KEY = "fms.finance.view";

function readView(): string | null {
  try {
    return sessionStorage.getItem(VIEW_KEY);
  } catch {
    return null;
  }
}

export function FinancePage(props: { api: ApiClient; farm: MeFarm; userId: string }): ReactNode {
  const { farmId } = useSync();
  const rights = useMemo(() => financeRights(props.farm.permissions), [props.farm.permissions]);
  const views = financeViews(rights);
  const [view, setViewState] = useState<FinanceView>(() => {
    const saved = readView();
    // A contributor comes for their own account, everyone else for the overview.
    const preferred = !rights.view && rights.fund ? "member" : views[0];
    return views.find((v) => v === saved) ?? preferred ?? "journal";
  });
  const [entry, setEntry] = useState<{ kind: EntryKind; loan?: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const accounts = useLocalEntities<TreasuryAccount>("finance.account").rows.map((a) => ({ ...a, id: a._id }));
  const categories = useCategories(props.api, props.farm.organization_id);
  const campaigns = useCampaigns();
  const loans = useRemote<LoanPosition[]>(props.api, rights.view ? `/farms/${farmId}/loans/positions/` : null,
                                          `fms.loans.${farmId}`);
  const balances = useRemote<AccountBalance[]>(props.api, rights.view ? `/farms/${farmId}/treasury-accounts/balances/` : null,
                                               `fms.balances.${farmId}`);
  const balanceMap = Object.fromEntries((balances.data ?? []).map((b) => [b.account, toAmount(b.balance)]));
  const currency = accounts.find((a) => a.role === "main")?.currency ?? accounts[0]?.currency ?? "XAF";

  const setView = (next: FinanceView) => {
    setViewState(next);
    setEntry(null);
    try {
      sessionStorage.setItem(VIEW_KEY, next);
    } catch {
      // ignored: a convenience only
    }
  };
  const examine = (id: string) => {
    setView("journal");
    setSelected(id);
  };
  const openEntry = (kind: EntryKind, loan?: string) => setEntry(loan ? { kind, loan } : { kind });

  if (views.length === 0) {
    return <EmptyState>Vous n'avez pas accès aux finances de cette exploitation.</EmptyState>;
  }
  const entryKinds: EntryKind[] = entry?.kind === "funding" ? ["funding"]
    : ["expense", "income", "transfer", ...((loans.data ?? []).length > 0 ? ["repayment" as const] : [])];
  const farmAccounts = accounts.filter((a) => a.role !== "member");

  return (
    <section className="flex flex-col gap-4" aria-label="Finances">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Finances</h2>
        {views.length > 1 && (
          <SubNav label="Finances" current={view} onChange={setView}
                  items={views.map((id) => ({ id, label: FINANCE_VIEW_LABELS[id] }))} />
        )}
        {rights.create && view !== "member" && !entry && (
          <Button onClick={() => openEntry("expense")}>+ Nouvelle opération</Button>
        )}
      </div>

      {entry && view !== "member" && (
        rights.view || farmAccounts.length > 0 ? (
          <TransactionForm key={`${entry.kind}-${entry.loan ?? ""}`} kinds={entryKinds} initialKind={entry.kind}
                           initialLoan={entry.loan} accounts={farmAccounts} categories={categories}
                           campaigns={campaigns} loans={loans.data ?? []} balances={balanceMap}
                           title={entry.kind === "funding" ? "Débloquer un emprunt ou enregistrer un apport direct" : undefined}
                           onDone={() => { setEntry(null); setView(view === "overview" ? "journal" : view); }}
                           onCancel={() => setEntry(null)} />
        ) : (
          <EmptyState hint="Votre rôle permet de saisir des dépenses, mais pas de consulter les comptes : demandez au gestionnaire financier (OPEN_QUESTIONS Q38)."
                      action={<Button variant="secondary" onClick={() => setEntry(null)}>Fermer</Button>}>
            Aucun compte disponible sur cet appareil.
          </EmptyState>
        )
      )}

      {view === "overview" && (
        <OverviewView api={props.api} rights={rights} accounts={accounts} onExamine={examine}
                      onNew={rights.create ? () => openEntry("expense") : undefined} />
      )}
      {view === "journal" && (
        <JournalView api={props.api} rights={rights} accounts={accounts} categories={categories} campaigns={campaigns}
                     selected={selected} onSelect={setSelected}
                     onNew={rights.create ? () => openEntry("expense") : undefined} />
      )}
      {view === "budgets" && (
        <BudgetView api={props.api} rights={rights} campaigns={campaigns} categories={categories} currency={currency} />
      )}
      {view === "accounts" && (
        <AccountsView api={props.api} rights={rights} accounts={accounts} loans={loans} defaultCurrency={currency}
                      onEntry={openEntry} />
      )}
      {view === "member" && (
        <MemberView api={props.api} rights={rights} userId={props.userId} categories={categories} />
      )}
    </section>
  );
}
