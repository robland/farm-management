/**
 * One transaction, with validation and rejection for validators. Both are online actions:
 * the server checks the version (`If-Match`) and the rights; a rejection needs a reason.
 */

import {
  financeRights, formatDate, formatDateTime, label, TRANSACTION_KIND_LABELS, transactionActions,
} from "@fms/shared";
import { router, useLocalSearchParams } from "expo-router";
import { type ReactNode, useState } from "react";
import { Modal, Text, TextInput, View } from "react-native";

import { Amount, TxBadges } from "../features/finance/components";
import { type Account, type Category, errorText, type Tx, useCategories } from "../features/finance/data";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, colors, Empty, Screen, styles, useBusy } from "../ui/components";

function Row({ name, value }: { name: string; value: string | undefined }): ReactNode {
  if (!value) return null;
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 12, paddingVertical: 8,
                   borderBottomWidth: 1, borderBottomColor: "#f5f5f4" }}>
      <Text style={styles.muted}>{name}</Text>
      <Text style={{ flexShrink: 1, textAlign: "right", color: colors.text }}>{value}</Text>
    </View>
  );
}

export default function FinanceTx(): ReactNode {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api, farm, notify, syncNow, online } = useSession();
  const rights = financeRights(farm?.permissions ?? []);
  const txs = useLocalEntities<Tx>("finance.transaction");
  const accounts = useLocalEntities<Account>("finance.account");
  const categories: Category[] = useCategories();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const tx = txs.find((t) => t._id === id);
  const queue = txs.filter((t) => !t._local && t.status === "submitted");
  const position = queue.findIndex((t) => t._id === id);

  if (!tx) return <Screen><Empty>Opération introuvable sur ce téléphone.</Empty></Screen>;
  const actions = tx._local ? { validate: false, reject: false } : transactionActions(tx, rights);
  const accountName = (accountId: string | undefined) => accounts.find((a) => a._id === accountId)?.name;
  const kindLabel = label(TRANSACTION_KIND_LABELS, tx.kind);

  const act = (action: "validate" | "reject", body: object) => run(async () => {
    setError(null);
    try {
      await api.send("POST", `/farms/${farm?.id ?? ""}/transactions/${tx._id}/${action}/`, body,
                     { "If-Match": String(tx.version ?? 1) });
      notify({ type: "success", farmId: farm?.id ?? null,
               text: `Opération ${action === "validate" ? "validée" : "rejetée"} : ${kindLabel.toLowerCase()}.` });
      setRejecting(false);
      await syncNow();
      // Next one in the queue, or back to the finances.
      const next = queue.find((t) => t._id !== tx._id);
      if (next) router.replace({ pathname: "/finance-tx", params: { id: next._id } });
      else router.back();
    } catch (err) {
      setError(errorText(err));
    }
  });

  return (
    <Screen>
      {position >= 0 && queue.length > 1 ? (
        <Text style={styles.muted}>Opération {position + 1} sur {queue.length} à valider</Text>
      ) : null}
      <View style={{ gap: 4 }}>
        <TxBadges tx={tx} local={tx._local} />
        <Text style={styles.title}>{tx.description || kindLabel}</Text>
        <Amount tx={tx} size={28} />
      </View>
      {tx.possible_duplicate && tx.status === "submitted" ? (
        <View style={[styles.card, { backgroundColor: "#fffbeb", borderColor: "#fde68a" }]}>
          <Text style={{ color: colors.warnText }}>
            <Text style={{ fontWeight: "700" }}>Doublon possible : </Text>
            opération semblable (même compte, montant, date et catégorie) saisie récemment par quelqu'un d'autre ou
            sur un autre téléphone.
          </Text>
        </View>
      ) : null}
      {tx.status === "rejected" && tx.rejected_reason ? (
        <Text style={[styles.card, { color: colors.danger }]}>Rejetée : {tx.rejected_reason}</Text>
      ) : null}
      <View style={[styles.card, { gap: 0, paddingVertical: 0 }]}>
        <Row name="Type" value={kindLabel} />
        <Row name="Date" value={formatDate(tx.business_date)} />
        <Row name="Compte" value={(tx.entries ?? []).map((e) => accountName(e.account)).filter(Boolean).join(" → ")
          || accountName(tx.account)} />
        <Row name="Catégorie" value={categories.find((c) => c.id === tx.category)?.name} />
        <Row name="Saisie" value={tx.created_at ? formatDateTime(tx.created_at) : undefined} />
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {actions.validate ? (
        <View style={{ flexDirection: "row", gap: 8 }}>
          <View style={{ flex: 1 }}>
            <Button variant="secondary" title="Rejeter" disabled={!online} onPress={() => { setReason(""); setRejecting(true); }} />
          </View>
          <View style={{ flex: 2 }}>
            <Button title="Valider" busy={busy && !rejecting} disabled={!online} onPress={() => void act("validate", {})} />
          </View>
        </View>
      ) : null}
      {actions.validate || tx._local ? (
        <Text style={[styles.muted, { textAlign: "center", fontSize: 12 }]}>
          {tx._local ? "Pas encore reçue par le serveur : la validation viendra ensuite."
            : online ? "Validation possible seulement en ligne." : "Hors ligne : la validation attend le retour du réseau."}
        </Text>
      ) : null}

      <Modal visible={rejecting} transparent animationType="fade" onRequestClose={() => setRejecting(false)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "center", padding: 24 }}>
          <View accessibilityViewIsModal style={{ backgroundColor: "white", borderRadius: 24, padding: 20, gap: 12 }}>
            <Text accessibilityRole="header" style={{ fontSize: 20, fontWeight: "500" }}>Rejeter cette opération ?</Text>
            <Text style={styles.label}>Motif, envoyé à l'auteur</Text>
            <TextInput accessibilityLabel="Motif du rejet" value={reason} onChangeText={setReason} multiline
                       style={[styles.input, styles.multiline]} />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
              <Button variant="secondary" title="Annuler" onPress={() => setRejecting(false)} />
              <Button variant="danger" title="Rejeter" busy={busy} disabled={!reason.trim()}
                      onPress={() => void act("reject", { reason: reason.trim() })} />
            </View>
          </View>
        </View>
      </Modal>
    </Screen>
  );
}
