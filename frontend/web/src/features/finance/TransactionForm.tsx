/**
 * Entry of an expense, income, transfer, loan repayment or funding. Saved on the device
 * and sent by the sync queue: the client id is the idempotency key (no double count).
 */

import {
  emptyTransactionForm, type EntryKind, entryAccounts, formatMoney, hasTransactionErrors, label, todayIso,
  TRANSACTION_KIND_LABELS, type TransactionErrors, type TransactionForm as Form, transactionPayload,
  transferTargets, toAmount, validateTransaction,
} from "@fms/shared";
import { type FormEvent, type ReactNode, useState } from "react";

import type { Campaign, FinanceCategory, LoanPosition, TreasuryAccount } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Button, Card, ErrorMessage, Field, Select, useBusy } from "../../ui/components";
import { Segmented } from "./ui";

const CATEGORY_KIND: Partial<Record<EntryKind, FinanceCategory["kind"]>> = {
  expense: "expense", income: "income", funding: "investment",
};

const SUBMIT_LABELS: Record<EntryKind, string> = {
  expense: "Enregistrer la dépense",
  income: "Enregistrer la recette",
  transfer: "Enregistrer le transfert",
  repayment: "Enregistrer le remboursement",
  funding: "Enregistrer l'apport",
};

const balanceLabel = (a: TreasuryAccount, balances: Record<string, string>) =>
  balances[a.id] === undefined ? `${a.name} (${a.currency})` : `${a.name} · ${formatMoney(balances[a.id] ?? "0", a.currency)}`;

export function TransactionForm(props: {
  kinds: EntryKind[];
  initialKind?: EntryKind;
  initialLoan?: string;
  accounts: TreasuryAccount[];
  categories: FinanceCategory[];
  campaigns: Campaign[];
  loans: LoanPosition[];
  /** Validated balances by account id, shown in the account lists when known. */
  balances?: Record<string, string>;
  title?: string;
  onDone: () => void;
  onCancel?: () => void;
}): ReactNode {
  const { record, farmId } = useSync();
  const { notify } = useNotifications();
  const today = todayIso();
  const balances = props.balances ?? {};
  const [draft, setDraft] = useState<Form>(() => ({
    ...emptyTransactionForm(props.initialKind ?? props.kinds[0] ?? "expense", today), loan: props.initialLoan ?? "" }));
  const [errors, setErrors] = useState<TransactionErrors>({});
  const [busy, run] = useBusy();

  const usableFor = (kind: EntryKind) => (kind === "repayment" ? props.accounts.filter((a) => a.role === "main")
    : kind === "transfer" || kind === "funding" ? props.accounts.filter((a) => a.is_active)
      : entryAccounts(props.accounts));
  const fromAccounts = usableFor(draft.kind);
  // A single possible account is preselected, also once the local accounts are loaded.
  const form: Form = { ...draft, account: draft.account || (fromAccounts.length === 1 ? fromAccounts[0]?.id ?? "" : "") };

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setDraft((f) => ({ ...f, [key]: value }));
  const setKind = (kind: EntryKind) => {
    setErrors({});
    setDraft((f) => ({ ...emptyTransactionForm(kind, f.business_date), amount: f.amount, description: f.description,
                       account: usableFor(kind).some((a) => a.id === f.account) ? f.account : "" }));
  };

  const account = props.accounts.find((a) => a.id === form.account);
  const currency = account?.currency ?? props.accounts[0]?.currency ?? "XAF";
  const categoryKind = CATEGORY_KIND[form.kind];
  const categories = props.categories.filter((c) => c.kind === categoryKind);
  const fromMember = account?.role === "member";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const found = validateTransaction(form, props.accounts, today);
      setErrors(found);
      if (hasTransactionErrors(found)) return;
      const payload = transactionPayload(form, currency);
      await record({ opType: "create", entityType: "finance.transaction", entityId: crypto.randomUUID(), payload });
      const saved = form.kind === "expense" || form.kind === "income" ? "enregistrée" : "enregistré";
      notify({ type: "success", farmId, action: { label: "Voir les finances", tab: "finances" },
               text: `${label(TRANSACTION_KIND_LABELS, form.kind)} de ${formatMoney(String(payload.amount), currency)} `
                 + `${saved} sur cet appareil. Le solde sera mis à jour après validation sur le serveur.` });
      props.onDone();
    });
  };

  return (
    <Card>
      <form onSubmit={submit} noValidate className="flex flex-col gap-4 p-4" aria-label={props.title ?? "Nouvelle opération"}>
        <h3 className="font-medium">{props.title ?? "Nouvelle opération"}</h3>
        {props.kinds.length > 1 && (
          <Segmented label="Type d'opération" value={form.kind} onChange={setKind}
                     options={props.kinds.map((k) => ({ id: k, label: k === "repayment" ? "Remboursement"
                       : label(TRANSACTION_KIND_LABELS, k) }))} />
        )}
        {fromAccounts.length === 0 && (
          <ErrorMessage>
            Aucun compte disponible. Synchronisez l'appareil ou demandez au gestionnaire financier d'en créer un.
          </ErrorMessage>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Date" type="date" value={form.business_date} max={today}
                 onChange={(e) => set("business_date", e.target.value)} error={errors.business_date} />
          <Field label={`Montant (${currency})`} inputMode="decimal" value={form.amount}
                 onChange={(e) => set("amount", e.target.value)} error={errors.amount}
                 hint="Devise du compte choisi." />

          <Select label={form.kind === "income" || form.kind === "funding" ? "Compte crédité"
                    : form.kind === "transfer" ? "Depuis" : "Compte débité"}
                  value={form.account} onChange={(e) => set("account", e.target.value)} error={errors.account}
                  disabled={form.kind === "repayment"}
                  options={fromAccounts.map((a) => ({ value: a.id, label: balanceLabel(a, balances) }))} />

          {form.kind === "transfer" && !fromMember && (
            <Select label="Vers" value={form.to_account} onChange={(e) => set("to_account", e.target.value)}
                    error={errors.to_account}
                    options={transferTargets(props.accounts, form.account)
                      .map((a) => ({ value: a.id, label: balanceLabel(a, balances) }))} />
          )}
          {categoryKind && (
            <Select label="Catégorie" value={form.category} onChange={(e) => set("category", e.target.value)}
                    error={errors.category}
                    options={categories.map((c) => ({ value: c.id, label: c.is_capex ? `${c.name} (investissement)` : c.name }))} />
          )}
          {(form.kind === "repayment" || (form.kind === "funding" && props.loans.length > 0 && !fromMember)) && (
            <Select label={form.kind === "repayment" ? "Emprunt" : "Emprunt débloqué (facultatif)"}
                    value={form.loan} onChange={(e) => set("loan", e.target.value)} error={errors.loan}
                    placeholder={form.kind === "repayment" ? "Choisir…" : "Aucun : apport direct"}
                    options={props.loans.map((l) => ({ value: l.loan, label: form.kind === "repayment"
                      ? `${l.lender} · reste dû ${formatMoney(toAmount(l.outstanding), l.currency)}` : l.lender }))} />
          )}
          {(form.kind === "expense" || form.kind === "income") && props.campaigns.length > 0 && (
            <Select label="Campagne (facultatif)" value={form.campaign} placeholder="Aucune"
                    onChange={(e) => set("campaign", e.target.value)}
                    options={props.campaigns.filter((c) => c.status !== "closed").map((c) => ({ value: c.id, label: c.name }))} />
          )}
          <div className="sm:col-span-2">
            <Field label="Description" value={form.description} onChange={(e) => set("description", e.target.value)}
                   hint={form.kind === "expense" ? "Fournisseur, objet, numéro de reçu…" : undefined} />
          </div>
        </div>
        {form.kind === "transfer" && (
          <p className="text-xs text-stone-500">
            {fromMember ? "Vers le compte principal de l'exploitation, dans la limite de votre solde validé."
              : "Un transfert ne compte ni en recette ni en dépense. Les comptes de membres ne reçoivent pas de transfert."}
          </p>
        )}
        {form.kind === "income" && (
          <p className="text-xs text-stone-500">
            Une subvention est une recette. Un apport de membre ou un prêt se saisit dans « Comptes et financements ».
          </p>
        )}
        {form.kind === "repayment" && (
          <p className="text-xs text-stone-500">
            Capital seulement, depuis le compte principal. Les intérêts se saisissent comme une dépense.
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-stone-200 pt-3">
          <p className="max-w-md text-xs text-stone-500">
            {fromMember && form.kind === "funding"
              ? "L'apport sera validé par le chef d'exploitation avant de compter dans votre solde."
              : "Enregistrée sur cet appareil, puis soumise à validation sur le serveur."}
          </p>
          <div className="flex gap-2">
            {props.onCancel && <Button variant="secondary" onClick={props.onCancel}>Annuler</Button>}
            <Button type="submit" disabled={busy}>{busy ? "Enregistrement…" : SUBMIT_LABELS[form.kind]}</Button>
          </div>
        </div>
      </form>
    </Card>
  );
}
