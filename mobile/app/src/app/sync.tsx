import { describeError, describeOperation, formatAge, formatDateTime, operationDetails } from "@fms/shared";
import type { LocalOperation } from "@fms/sync-core";
import { type ReactNode, useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";

import { useSession } from "../session/Session";
import { Button, colors, Empty, LocalStatus, Screen, styles } from "../ui/components";

const PROBLEM = new Set(["failed", "conflict"]);

export default function Sync(): ReactNode {
  const { store, engine, farm, revision, refresh, syncNow, syncing, online, lastSyncAt } = useSession();
  const [ops, setOps] = useState<LocalOperation[]>([]);

  useEffect(() => {
    if (store && farm) {
      void store.listOperations(farm.id).then((list) =>
        // Problems first (they need the user), then in sending order.
        setOps(list.sort((a, b) => Number(PROBLEM.has(b.status)) - Number(PROBLEM.has(a.status))
          || a.createdAt.localeCompare(b.createdAt))));
    }
  }, [store, farm, revision]);

  if (!engine || !farm) return <Empty>Aucune exploitation sélectionnée.</Empty>;

  const abandon = (op: LocalOperation) => {
    const details = operationDetails(op);
    // Sensitive operation: explicit confirmation (CLAUDE.md §7).
    Alert.alert("Abandonner cette saisie ?",
      `« ${describeOperation(op)} » ne sera jamais envoyée au serveur. Notez son contenu si vous devez la `
      + `ressaisir.${details.length ? `\n\n${details.join("\n")}` : ""}`, [
        { text: "Annuler", style: "cancel" },
        { text: "Abandonner", style: "destructive",
          onPress: () => void engine.abandon(op.opId, farm.id).then(refresh) },
      ]);
  };

  const problems = ops.filter((op) => PROBLEM.has(op.status)).length;
  return (
    <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
      <View style={styles.card}>
        <Text style={{ fontWeight: "700", color: online ? colors.primary : colors.offline }}>
          {online ? "En ligne" : "Hors ligne : nouvel essai automatique au retour du réseau"}
        </Text>
        <Text style={styles.muted}>
          Dernière synchronisation réussie : {lastSyncAt ? formatAge(lastSyncAt) : "pas encore depuis l'ouverture"}
        </Text>
        {problems ? (
          <Text style={{ color: colors.danger, fontWeight: "600" }}>
            {problems === 1 ? "1 saisie demande" : `${problems} saisies demandent`} votre attention.
          </Text>
        ) : null}
      </View>
      <Button title={syncing ? "Synchronisation…" : "Synchroniser maintenant"} busy={syncing}
              onPress={() => void syncNow()} />
      {ops.length === 0 ? <Empty>Toutes les données sont synchronisées.</Empty> : ops.map((op) => (
        <View key={op.opId} style={[styles.card, PROBLEM.has(op.status) && { borderColor: colors.danger }]}>
          <Text style={{ fontWeight: "600", fontSize: 16 }}>{describeOperation(op)}</Text>
          <Text style={styles.muted}>Saisie le {formatDateTime(op.createdAt)}</Text>
          <LocalStatus status={op.status} />
          {op.lastError ? <Text style={styles.error}>{describeError(op.lastError)}</Text> : null}
          {PROBLEM.has(op.status) ? (
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Button variant="secondary" title="Réessayer"
                        onPress={() => void engine.retry(op.opId, farm.id).then(syncNow)} />
              </View>
              <View style={{ flex: 1 }}>
                <Button variant="danger" title="Abandonner" onPress={() => abandon(op)} />
              </View>
            </View>
          ) : null}
        </View>
      ))}
    </Screen>
  );
}
