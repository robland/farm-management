import { formatDate, formatMoney } from "@fms/shared";
import * as Crypto from "expo-crypto";
import { router } from "expo-router";
import { type ReactNode, useEffect, useState } from "react";
import { Text } from "react-native";

import { normalizeDecimal, todayIso, validateAmount } from "../features/validation";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, Choice, Empty, Field, Screen, styles, useBusy } from "../ui/components";

interface Account { id: string; name: string; currency: string; is_active: boolean }
interface Category { id: string; name: string }

export default function Expense(): ReactNode {
  const { record, api, farm, store, notify, syncNow, syncing } = useSession();
  const accounts = useLocalEntities<Account>("finance.account").filter((a) => a.is_active);
  const [categories, setCategories] = useState<Category[]>([]);
  const [account, setAccount] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [busy, run] = useBusy();

  useEffect(() => {
    if (!farm || !store) return;
    const key = `categories.${farm.organization_id}`;
    void store.getValue<Category[]>(key).then((cached) => cached && setCategories(cached));
    // Organization data: refreshed online, cached locally for offline entry.
    api.request<{ results: Category[] }>(
      "GET", `/organizations/${farm.organization_id}/finance-categories/?kind=expense`)
      .then((page) => {
        setCategories(page.results);
        void store.setValue(key, page.results);
      })
      .catch(() => undefined);
  }, [api, farm, store]);

  // One account: preselected.
  const selected = account ?? (accounts.length === 1 ? accounts[0]?.id ?? null : null);
  const currency = accounts.find((a) => a.id === selected)?.currency ?? "XAF";

  // useBusy: a double tap must never create two transactions (two client ids).
  const submit = () => void run(async () => {
    const found = { account: selected ? null : "Compte obligatoire.",
                    category: category ? null : "Catégorie obligatoire.",
                    amount: validateAmount(amount, currency) };
    setErrors(found);
    if (Object.values(found).some(Boolean) || !selected || !category) return;
    // The client id is the idempotency key: never counted twice (OFFLINE_SYNC.md §7).
    await record({
      opType: "create", entityType: "finance.transaction", entityId: Crypto.randomUUID(),
      payload: { kind: "expense", account: selected, category, amount: normalizeDecimal(amount), currency,
                 business_date: todayIso(), description: description.trim() },
    });
    notify({ type: "success", farmId: farm?.id ?? null,
             text: `Dépense de ${formatMoney(normalizeDecimal(amount), currency)} enregistrée sur le téléphone. `
               + "Le solde sera mis à jour après validation sur le serveur." });
    router.back();
  });

  if (accounts.length === 0) {
    return (
      <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
        <Empty hint="Les comptes arrivent avec la synchronisation. Sinon, demandez au gestionnaire financier d'en créer un."
               action={{ title: syncing ? "Synchronisation…" : "Synchroniser maintenant", onPress: () => void syncNow() }}>
          Aucun compte de trésorerie sur ce téléphone.
        </Empty>
      </Screen>
    );
  }
  return (
    <Screen>
      <Choice label="Compte" value={selected} onChange={setAccount} error={errors.account}
              options={accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.currency})` }))} />
      {categories.length === 0 ? (
        <Text style={styles.error}>
          Catégories indisponibles : connectez-vous une première fois au réseau pour les charger.
        </Text>
      ) : (
        <Choice label="Catégorie" value={category} onChange={setCategory} error={errors.category}
                options={categories.map((c) => ({ value: c.id, label: c.name }))} />
      )}
      <Field label={`Montant (${currency})`} value={amount} onChangeText={setAmount}
             keyboardType="decimal-pad" error={errors.amount}
             hint={amount && !validateAmount(amount, currency) ? formatMoney(normalizeDecimal(amount), currency)
               : undefined} />
      <Field label="Description" value={description} onChangeText={setDescription}
             placeholder="Fournisseur, objet, n° de reçu…" />
      <Text style={styles.muted}>
        Dépense datée d'aujourd'hui ({formatDate(todayIso())}). Le solde n'est mis à jour qu'après validation sur
        le serveur.
      </Text>
      <Button title="Enregistrer la dépense" busy={busy} onPress={submit} />
    </Screen>
  );
}
