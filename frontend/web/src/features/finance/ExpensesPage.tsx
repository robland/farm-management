import { formatDate, formatMoney, label, TRANSACTION_KIND_LABELS, TRANSACTION_STATUS_LABELS,
         todayIso } from "@fms/shared";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { FinanceCategory, Paginated, Transaction, TreasuryAccount } from "../../api/types";
import { useLocalEntities, useSync } from "../../sync/SyncContext";
import { useNotifications } from "../../notifications/NotificationsContext";
import { Button, Card, EmptyState, ErrorMessage, Field, Loading, LocalStatus, SectionHeader, Select,
         useBusy } from "../../ui/components";
import { type Errors, type ExpenseForm, hasErrors, normalizeDecimal, validateExpense } from "../validation";

const CATEGORY_CACHE = "fms.categories";

const STATUS_STYLES: Record<string, string> = {
  submitted: "bg-amber-100 text-amber-900",
  validated: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  reversed: "bg-stone-200 text-stone-600 line-through",
};

/** Categories are organization data: fetched online, cached for offline entry. */
function useCategories(api: ApiClient, organizationId: string): FinanceCategory[] {
  const key = `${CATEGORY_CACHE}.${organizationId}`;
  const [categories, setCategories] = useState<FinanceCategory[]>(() => {
    const cached = localStorage.getItem(key);
    return cached ? (JSON.parse(cached) as FinanceCategory[]) : [];
  });
  useEffect(() => {
    api.request<Paginated<FinanceCategory>>(
      "GET", `/organizations/${organizationId}/finance-categories/?kind=expense`)
      .then((page) => {
        setCategories(page.results);
        localStorage.setItem(key, JSON.stringify(page.results));
      })
      .catch(() => undefined); // offline: keep the cached list
  }, [api, organizationId, key]);
  return categories;
}

export function ExpensesPage(props: { api: ApiClient; organizationId: string; canCreate: boolean }): ReactNode {
  const { record, farmId } = useSync();
  const accounts = useLocalEntities<TreasuryAccount>("finance.account");
  const transactions = useLocalEntities<Transaction & { category?: string }>("finance.transaction");
  const categories = useCategories(props.api, props.organizationId);
  const today = todayIso();
  const activeAccounts = accounts.rows.filter((a) => a.is_active);
  // A single account is preselected: one less step in the field.
  const defaultAccount = activeAccounts.length === 1 ? activeAccounts[0]?.id ?? "" : "";
  const empty: ExpenseForm = { account: defaultAccount, category: "", amount: "", business_date: today,
                               description: "" };
  const [form, setForm] = useState(empty);
  const [errors, setErrors] = useState<Errors<ExpenseForm>>({});
  const [busy, run] = useBusy();
  const { notify } = useNotifications();
  const account = form.account || defaultAccount;
  const currency = activeAccounts.find((a) => a.id === account)?.currency ?? "XAF";

  // A second click would create a second transaction with a new id: useBusy blocks it.
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const values = { ...form, account };
      const found = validateExpense(values, currency, today);
      setErrors(found);
      if (hasErrors(found)) return;
      // The client transaction id is the idempotency key: it can never be counted twice.
      await record({
        opType: "create",
        entityType: "finance.transaction",
        entityId: crypto.randomUUID(),
        payload: {
          kind: "expense",
          account,
          category: values.category,
          amount: normalizeDecimal(values.amount),
          currency,
          business_date: values.business_date,
          description: values.description.trim(),
        },
      });
      notify({ type: "success", farmId,
               text: `Dépense de ${formatMoney(normalizeDecimal(values.amount), currency)} enregistrée sur cet `
                 + "appareil. Le solde sera mis à jour après validation sur le serveur." });
      // Keep account and date: several receipts are often entered in a row.
      setForm({ ...empty, account, business_date: values.business_date });
    });
  };

  const set = (key: keyof ExpenseForm) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });
  const categoryName = (id: string | undefined) => categories.find((c) => c.id === id)?.name;
  const sorted = [...transactions.rows].sort((a, b) => b.business_date.localeCompare(a.business_date));

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader title="Dépenses" />
      {props.canCreate && (
        <Card>
          <form onSubmit={submit} noValidate className="grid gap-3 p-4 sm:grid-cols-2">
            <h3 className="font-medium sm:col-span-2">Nouvelle dépense</h3>
            {activeAccounts.length === 0 && !accounts.loading && (
              <div className="sm:col-span-2">
                <ErrorMessage>
                  Aucun compte de trésorerie disponible. Synchronisez l'appareil ou demandez au gestionnaire
                  financier d'en créer un.
                </ErrorMessage>
              </div>
            )}
            <Select label="Compte" value={account} onChange={set("account")} error={errors.account}
                    options={activeAccounts.map((a) => ({ value: a.id, label: `${a.name} (${a.currency})` }))} />
            <Select label="Catégorie" value={form.category} onChange={set("category")} error={errors.category}
                    options={categories.map((c) => ({ value: c.id, label: c.name }))} />
            <Field label={`Montant (${currency})`} inputMode="decimal" value={form.amount}
                   onChange={set("amount")} error={errors.amount} />
            <Field label="Date" type="date" value={form.business_date} max={today}
                   onChange={set("business_date")} error={errors.business_date} />
            <div className="sm:col-span-2">
              <Field label="Description" value={form.description} onChange={set("description")}
                     hint="Fournisseur, objet, numéro de reçu…" />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={busy}>{busy ? "Enregistrement…" : "Enregistrer la dépense"}</Button>
            </div>
          </form>
        </Card>
      )}
      <h3 className="font-medium">Transactions récentes</h3>
      {transactions.loading ? <Loading /> : sorted.length === 0 ? (
        <EmptyState>Aucune transaction.</EmptyState>
      ) : (
        <Card>
          <ul className="divide-y divide-stone-200">
            {sorted.map((tx) => (
              <li key={tx._id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                <span className="flex min-w-0 flex-col">
                  <span className="font-medium">
                    {tx.description || categoryName(tx.category) || label(TRANSACTION_KIND_LABELS, tx.kind)}
                  </span>
                  <span className="text-xs text-stone-500">
                    {formatDate(tx.business_date)}
                    {tx.description && categoryName(tx.category) ? ` · ${categoryName(tx.category)}` : ""}
                  </span>
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium tabular-nums">{formatMoney(tx.amount, tx.currency)}</span>
                  {tx._local ? <LocalStatus status={tx._local} /> : (
                    <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLES[tx.status] ?? ""}`}>
                      {label(TRANSACTION_STATUS_LABELS, tx.status)}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}
