/**
 * Offline entry of an expense, income, transfer or member contribution. Saved on the phone
 * and sent by the sync queue; the client id is the idempotency key (never counted twice).
 */

import {
  emptyTransactionForm, type EntryKind, entryAccounts, financeRights, formatMoney, hasTransactionErrors, label,
  todayIso, TRANSACTION_KIND_LABELS, type TransactionErrors, type TransactionForm, transactionPayload,
  transferTargets, validateTransaction,
} from "@fms/shared";
import * as Crypto from "expo-crypto";
import { router, useLocalSearchParams } from "expo-router";
import { type ReactNode, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { type Account, useCategories, useRemote } from "../features/finance/data";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, Choice, colors, Empty, Field, Screen, styles, useBusy } from "../ui/components";

const ENTRY_KINDS: EntryKind[] = ["expense", "income", "transfer"];
const CATEGORY_KIND: Partial<Record<EntryKind, string>> = { expense: "expense", income: "income", funding: "investment" };
const SUBMIT: Record<EntryKind, string> = {
  expense: "Enregistrer la dépense", income: "Enregistrer la recette", transfer: "Enregistrer le transfert",
  repayment: "Enregistrer le remboursement", funding: "Enregistrer l'apport",
};

export default function FinanceEntry(): ReactNode {
  const params = useLocalSearchParams<{ kind?: string; account?: string }>();
  const { record, farm, notify, syncNow, syncing, me } = useSession();
  const rights = financeRights(farm?.permissions ?? []);
  const local = useLocalEntities<Account>("finance.account").map((a) => ({ ...a, id: a._id }));
  // Without finance.view, the member account is not synced: it is listed by the server (Q35).
  const own = useRemote<{ results: Account[] }>(!rights.view && farm ? `/farms/${farm.id}/treasury-accounts/?page_size=200` : null,
                                                `my-accounts.${farm?.id ?? ""}`);
  const accounts = rights.view ? local : [...local, ...(own.data?.results ?? []).filter((a) => a.holder === me?.user.id)];
  const memberMode = params.kind === "funding" || Boolean(params.account);
  const kinds = memberMode ? [(params.kind ?? "funding") as EntryKind] : ENTRY_KINDS;
  const categories = useCategories();
  const today = todayIso();
  const [draft, setDraft] = useState<TransactionForm>(() => ({
    ...emptyTransactionForm(kinds.includes(params.kind as EntryKind) ? params.kind as EntryKind : "expense", today),
    account: params.account ?? "" }));
  const [errors, setErrors] = useState<TransactionErrors>({});
  const [busy, run] = useBusy();

  const usable = draft.kind === "transfer" || draft.kind === "funding" ? accounts.filter((a) => a.is_active)
    : entryAccounts(accounts);
  // A single possible account is preselected.
  const form = { ...draft, account: draft.account || (usable.length === 1 ? usable[0]?.id ?? "" : "") };
  const account = accounts.find((a) => a.id === form.account);
  const currency = account?.currency ?? "XAF";
  const fromMember = account?.role === "member";
  const set = <K extends keyof TransactionForm>(key: K, value: TransactionForm[K]) =>
    setDraft((f) => ({ ...f, [key]: value }));
  const categoryKind = CATEGORY_KIND[form.kind];

  const submit = () => void run(async () => {
    const found = validateTransaction(form, accounts, today);
    setErrors(found);
    if (hasTransactionErrors(found)) return;
    const payload = transactionPayload(form, currency);
    await record({ opType: "create", entityType: "finance.transaction", entityId: Crypto.randomUUID(), payload });
    const saved = form.kind === "expense" || form.kind === "income" ? "enregistrée" : "enregistré";
    notify({ type: "success", farmId: farm?.id ?? null,
             text: `${label(TRANSACTION_KIND_LABELS, form.kind)} de ${formatMoney(String(payload.amount), currency)} `
               + `${saved} sur le téléphone. Le solde sera mis à jour après validation sur le serveur.` });
    router.back();
  });

  if (accounts.length === 0) {
    return (
      <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
        <Empty hint={rights.view ? "Les comptes arrivent avec la synchronisation. Sinon, demandez au gestionnaire financier d'en créer un."
          : "Votre rôle permet de saisir, mais pas de consulter les comptes (OPEN_QUESTIONS Q38)."}
               action={{ title: syncing ? "Synchronisation…" : "Synchroniser maintenant", onPress: () => void syncNow() }}>
          Aucun compte de trésorerie sur ce téléphone.
        </Empty>
      </Screen>
    );
  }
  return (
    <Screen>
      {kinds.length > 1 && (
        <View accessibilityRole="radiogroup" accessibilityLabel="Type d'opération"
              style={{ flexDirection: "row", borderWidth: 1, borderColor: colors.border, borderRadius: 22, overflow: "hidden" }}>
          {kinds.map((k) => {
            const selected = k === form.kind;
            return (
              <Pressable key={k} accessibilityRole="radio" accessibilityState={{ selected }}
                         onPress={() => { setErrors({}); setDraft((f) => ({ ...emptyTransactionForm(k, f.business_date),
                           amount: f.amount, description: f.description })); }}
                         style={{ flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center",
                                  backgroundColor: selected ? colors.primary : "white" }}>
                <Text style={selected ? styles.primaryText : styles.chipText}>{label(TRANSACTION_KIND_LABELS, k)}</Text>
              </Pressable>
            );
          })}
        </View>
      )}
      <Field label={`Montant (${currency})`} value={form.amount} onChangeText={(v) => set("amount", v)}
             keyboardType="decimal-pad" error={errors.amount}
             hint={form.amount && !errors.amount ? "Devise du compte choisi." : undefined} />
      <Choice label={form.kind === "income" || form.kind === "funding" ? "Reçu sur" : form.kind === "transfer" ? "Depuis" : "Payé avec"}
              value={form.account || null} onChange={(v) => set("account", v)} error={errors.account}
              options={usable.map((a) => ({ value: a.id, label: a.name }))} />
      {form.kind === "transfer" && !fromMember && (
        <Choice label="Vers" value={form.to_account || null} onChange={(v) => set("to_account", v)} error={errors.to_account}
                options={transferTargets(accounts, form.account).map((a) => ({ value: a.id, label: a.name }))} />
      )}
      {categoryKind ? (
        categories.filter((c) => c.kind === categoryKind).length === 0 ? (
          <Text style={styles.error}>Catégories indisponibles : connectez-vous une première fois au réseau pour les charger.</Text>
        ) : (
          <Choice label="Catégorie" value={form.category || null} onChange={(v) => set("category", v)} error={errors.category}
                  options={categories.filter((c) => c.kind === categoryKind).map((c) => ({ value: c.id, label: c.name }))} />
        )
      ) : null}
      <Field label="Date" value={form.business_date} onChangeText={(v) => set("business_date", v.trim())}
             error={errors.business_date} hint="Format AAAA-MM-JJ. Aujourd'hui par défaut." autoCorrect={false} />
      <Field label="Description (facultatif)" value={form.description} onChangeText={(v) => set("description", v)}
             placeholder={form.kind === "expense" ? "Fournisseur, objet, n° de reçu…" : undefined} />
      {form.kind === "transfer" ? (
        <Text style={styles.muted}>
          {fromMember ? "Vers le compte principal de l'exploitation, dans la limite de votre solde validé."
            : "Un transfert ne compte ni en recette ni en dépense."}
        </Text>
      ) : null}
      <Button title={SUBMIT[form.kind]} busy={busy} onPress={submit} />
      <Text style={[styles.muted, { textAlign: "center", fontSize: 12 }]}>
        {fromMember && form.kind === "funding" ? "L'apport sera validé par le chef d'exploitation avant de compter dans votre solde."
          : "Gardée sur le téléphone, puis envoyée pour validation. Un double appui n'enregistre qu'une seule fois."}
      </Text>
    </Screen>
  );
}
