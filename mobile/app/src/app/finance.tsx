/** Finances on the phone: last known balances, quick entries, validation queue, recent operations. */

import {
  financeRights, formatDate, formatDateTime, formatMoney, isNegative, label, toAmount, TRANSACTION_KIND_LABELS,
} from "@fms/shared";
import { router } from "expo-router";
import type { ReactNode } from "react";
import { Pressable, Text, View } from "react-native";

import { Amount, TxBadges } from "../features/finance/components";
import { type Account, type Tx, useRemote } from "../features/finance/data";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, colors, Empty, Screen, SectionTitle, styles } from "../ui/components";

interface Balance { account: string; name: string; role: string; currency: string; balance: string | number;
                    is_active: boolean }

export default function Finance(): ReactNode {
  const { farm, syncNow, syncing } = useSession();
  const rights = financeRights(farm?.permissions ?? []);
  const balances = useRemote<Balance[]>(rights.view && farm ? `/farms/${farm.id}/treasury-accounts/balances/` : null,
                                        `balances.${farm?.id ?? ""}`);
  const accounts = useLocalEntities<Account>("finance.account");
  const txs = useLocalEntities<Tx>("finance.transaction")
    .sort((a, b) => b.business_date.localeCompare(a.business_date) || (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  const pending = txs.filter((t) => !t._local && t.status === "submitted");
  const duplicates = pending.filter((t) => t.possible_duplicate).length;
  const shown = (balances.data ?? []).filter((b) => b.role !== "member" && b.is_active);
  const accountName = (id: string | undefined) => accounts.find((a) => a._id === id)?.name ?? "";
  const where = (t: Tx) => {
    const entries = t.entries ?? [];
    if (t.kind === "transfer" && entries.length === 2) {
      return `${accountName(entries.find((e) => e.amount.startsWith("-"))?.account)} → ${
        accountName(entries.find((e) => !e.amount.startsWith("-"))?.account)}`;
    }
    return accountName(entries[0]?.account ?? t.account);
  };

  return (
    <Screen onRefresh={() => { void syncNow(); balances.reload(); }} refreshing={syncing}>
      {rights.view && (
        <View style={styles.card}>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={{ fontWeight: "700" }}>Soldes validés</Text>
            {balances.fetchedAt ? <Text style={[styles.muted, { fontSize: 12 }]}>au {formatDateTime(balances.fetchedAt)}</Text> : null}
          </View>
          {shown.length === 0 ? (
            <Text style={styles.muted}>{balances.error ? "Soldes indisponibles sans réseau." : "Aucun compte."}</Text>
          ) : shown.map((b) => (
            <View key={b.account} style={{ flexDirection: "row", justifyContent: "space-between", gap: 8 }}>
              <Text style={{ flexShrink: 1 }}>{b.name}</Text>
              <Text style={{ fontWeight: "700", color: isNegative(toAmount(b.balance)) ? colors.danger : colors.text }}>
                {isNegative(toAmount(b.balance)) ? "−" : ""}{formatMoney(toAmount(b.balance).replace(/^-/, ""), b.currency)}
              </Text>
            </View>
          ))}
          <Text style={[styles.muted, { fontSize: 12 }]}>
            Hors ligne, les soldes restent ceux de la dernière synchronisation. Vos saisies non envoyées n'y figurent pas.
          </Text>
        </View>
      )}

      {rights.create && (
        <View style={{ flexDirection: "row", gap: 8 }}>
          {(["expense", "income", "transfer"] as const).map((kind) => (
            <View key={kind} style={{ flex: 1 }}>
              <Button variant={kind === "expense" ? "primary" : "secondary"} title={label(TRANSACTION_KIND_LABELS, kind)}
                      onPress={() => router.push({ pathname: "/finance-entry", params: { kind } })} />
            </View>
          ))}
        </View>
      )}

      {rights.validate && pending.length > 0 && (
        <Pressable accessibilityRole="button" onPress={() => router.push({ pathname: "/finance-tx", params: { id: pending[0]?._id ?? "" } })}
                   style={[styles.card, { borderColor: "#d97706", borderLeftWidth: 6 }]}>
          <Text style={{ fontWeight: "700", color: colors.warnText }}>
            {pending.length} opération{pending.length > 1 ? "s" : ""} à valider
          </Text>
          {duplicates ? <Text style={styles.muted}>Dont {duplicates} doublon{duplicates > 1 ? "s" : ""} possible{duplicates > 1 ? "s" : ""}</Text> : null}
        </Pressable>
      )}

      <SectionTitle>Dernières opérations</SectionTitle>
      {txs.length === 0 ? (
        <Empty hint={rights.view ? undefined : "Seules vos saisies faites sur ce téléphone apparaissent ici."}>
          Aucune opération.
        </Empty>
      ) : txs.slice(0, 30).map((t) => (
        <Pressable key={t._id} accessibilityRole="button" disabled={Boolean(t._local)}
                   onPress={() => router.push({ pathname: "/finance-tx", params: { id: t._id } })}
                   style={({ pressed }) => [styles.card, { flexDirection: "row", alignItems: "center", gap: 10 },
                                            pressed && styles.pressed]}>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={{ fontWeight: "600" }}>{t.description || label(TRANSACTION_KIND_LABELS, t.kind)}</Text>
            <Text style={styles.muted}>{[where(t), formatDate(t.business_date)].filter(Boolean).join(" · ")}</Text>
            <TxBadges tx={t} local={t._local} />
          </View>
          <Amount tx={t} />
        </Pressable>
      ))}
      <Text style={[styles.muted, { fontSize: 12, textAlign: "center" }]}>
        Budgets, emprunts et gestion des comptes : sur l'application Web.
      </Text>
    </Screen>
  );
}
