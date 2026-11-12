/**
 * The user's member account (Q35): balance, contributions waiting for validation, and the
 * two actions of a contributor. A contributor sees nothing else of the farm's finances.
 */

import { financeRights, formatDate, formatMoney, label, toAmount, TRANSACTION_KIND_LABELS } from "@fms/shared";
import { router } from "expo-router";
import type { ReactNode } from "react";
import { Text, View } from "react-native";

import { Amount, TxBadges } from "../features/finance/components";
import { type Account, errorText, type Tx, useRemote } from "../features/finance/data";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, Empty, Screen, SectionTitle, styles, useBusy } from "../ui/components";

interface Statement { account: string; currency: string; contributed: string | number;
                      pending_contributions: string | number; transferred_to_treasury: string | number;
                      balance: string | number }

export default function Member(): ReactNode {
  const { api, farm, me, notify, syncNow, syncing } = useSession();
  const rights = financeRights(farm?.permissions ?? []);
  const farmId = farm?.id ?? "";
  const accounts = useRemote<{ results: Account[] }>(farm ? `/farms/${farmId}/treasury-accounts/?page_size=200` : null,
                                                     `my-accounts.${farmId}`);
  const statements = useRemote<Statement[]>(farm ? `/farms/${farmId}/treasury-accounts/members/` : null,
                                            `my-statement.${farmId}`);
  const local = useLocalEntities<Tx>("finance.transaction");
  // Without finance.view nothing financial is synced: the server lists the user's own movements.
  const listed = useRemote<{ results: Tx[] }>(farm && !rights.view ? `/farms/${farmId}/transactions/?page_size=200` : null,
                                              `my-transactions.${farmId}`);
  const txs = [...local, ...(listed.data?.results ?? []).filter((t) => !local.some((l) => l._id === t.id))
    .map((t) => ({ ...t, _id: t.id, _local: null }))].sort((a, b) => b.business_date.localeCompare(a.business_date));
  const [busy, run] = useBusy();
  const mine = (accounts.data?.results ?? []).find((a) => a.role === "member" && a.holder === me?.user.id);
  const statement = (statements.data ?? []).find((s) => s.account === mine?.id);
  const movements = txs.filter((t) => mine && ((t.entries ?? []).some((e) => e.account === mine.id) || t.account === mine.id));

  const open = () => void run(async () => {
    try {
      await api.request("POST", `/farms/${farmId}/treasury-accounts/mine/`, {});
      notify({ type: "success", farmId, text: "Votre compte de membre est ouvert." });
      accounts.reload();
      statements.reload();
    } catch (error) {
      notify({ type: "issue", farmId, text: `Ouverture du compte impossible. ${errorText(error)}` });
    }
  });
  const refresh = () => {
    void syncNow();
    accounts.reload();
    statements.reload();
    listed.reload();
  };

  if (!mine) {
    return (
      <Screen onRefresh={refresh} refreshing={syncing}>
        <Empty hint={accounts.error ?? "Il reçoit vos apports à l'exploitation, que vous transférez ensuite à sa trésorerie."}
               action={{ title: busy ? "Ouverture…" : "Ouvrir mon compte de membre", onPress: open }}>
          Vous n'avez pas encore de compte de membre.
        </Empty>
      </Screen>
    );
  }
  const balance = toAmount(statement?.balance);
  const money = (v: string | number | undefined) => formatMoney(toAmount(v), mine.currency);
  return (
    <Screen onRefresh={refresh} refreshing={syncing}>
      <View style={styles.card}>
        <Text style={styles.muted}>Solde disponible</Text>
        <Text style={{ fontSize: 28, fontWeight: "700" }}>{formatMoney(balance, mine.currency)}</Text>
        <View style={{ flexDirection: "row", gap: 8, borderTopWidth: 1, borderTopColor: "#f5f5f4", paddingTop: 8 }}>
          {[["Apporté", statement?.contributed], ["En attente", statement?.pending_contributions],
            ["Versé à la ferme", statement?.transferred_to_treasury]].map(([name, value]) => (
            <View key={String(name)} style={{ flex: 1 }}>
              <Text style={[styles.muted, { fontSize: 12 }]}>{String(name)}</Text>
              <Text style={{ fontWeight: "700" }}>{money(value as string | number | undefined)}</Text>
            </View>
          ))}
        </View>
        {statements.fetchedAt && statements.error ? (
          <Text style={[styles.muted, { fontSize: 12 }]}>Hors ligne : montants de la dernière connexion.</Text>
        ) : null}
      </View>
      <Button title="Apporter des fonds" subtitle="Validé par le chef d'exploitation"
              onPress={() => router.push({ pathname: "/finance-entry", params: { kind: "funding", account: mine.id } })} />
      <Button variant="secondary" title="Transférer à la trésorerie" subtitle={`Jusqu'à ${formatMoney(balance, mine.currency)} (solde validé)`}
              onPress={() => router.push({ pathname: "/finance-entry", params: { kind: "transfer", account: mine.id } })} />
      <SectionTitle>Mes mouvements</SectionTitle>
      {movements.length === 0 ? <Text style={styles.muted}>Aucun mouvement.</Text>
        : movements.map((t) => (
          <View key={t._id} style={[styles.card, { flexDirection: "row", alignItems: "center", gap: 10 }]}>
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={{ fontWeight: "600" }}>
                {t.kind === "transfer" ? "Transfert vers la trésorerie" : label(TRANSACTION_KIND_LABELS, t.kind)}
              </Text>
              <Text style={styles.muted}>{formatDate(t.business_date)}</Text>
              <TxBadges tx={t} local={t._local} />
            </View>
            <Amount tx={t.kind === "transfer" ? { ...t, kind: "expense" } : t} />
          </View>
        ))}
      {!rights.view ? (
        <Text style={[styles.muted, { textAlign: "center", fontSize: 12 }]}>
          Rôle « Membre contributeur » : vous ne voyez que votre propre compte.
        </Text>
      ) : null}
    </Screen>
  );
}
