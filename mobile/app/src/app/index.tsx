import { formatAge, groupTasks, roleLabel, todayIso } from "@fms/shared";
import { NetworkError } from "@fms/sync-core";
import { router } from "expo-router";
import { type ReactNode, useRef, useState } from "react";
import { ActivityIndicator, Alert, Pressable, Text, type TextInputInstance, View } from "react-native";

import { useLocalEntities, useSession } from "../session/Session";
import { Button, colors, Empty, Field, Notice, PasswordField, Screen, styles, useBusy } from "../ui/components";

function LoginForm(): ReactNode {
  const { login } = useSession();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const passwordRef = useRef<TextInputInstance>(null);

  const submit = () => void run(async () => {
    if (!identifier.trim() || !password) {
      setError("Identifiant et mot de passe obligatoires.");
      return;
    }
    setError(null);
    try {
      await login(identifier.trim(), password);
    } catch (err) {
      setError(err instanceof NetworkError ? "Serveur injoignable : la première connexion nécessite le réseau."
        : "Identifiants invalides.");
    }
  });

  return (
    <View style={{ gap: 12 }}>
      <Text style={styles.title}>Gestion agricole</Text>
      <Text style={styles.muted}>Connectez-vous pour accéder à vos exploitations.</Text>
      <Field label="E-mail ou téléphone" value={identifier} onChangeText={setIdentifier}
             autoCapitalize="none" autoCorrect={false} keyboardType="email-address" autoComplete="username"
             returnKeyType="next" onSubmitEditing={() => passwordRef.current?.focus()}
             hint="Téléphone au format international, avec l'indicatif du pays (+…)." />
      <PasswordField ref={passwordRef} label="Mot de passe" value={password} onChangeText={setPassword}
                     autoComplete="current-password" returnKeyType="go" onSubmitEditing={submit} />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Button title={busy ? "Connexion…" : "Se connecter"} busy={busy} onPress={submit} />
    </View>
  );
}

/** Coloured connection and queue status; tapping it opens the sync screen. */
function SyncStatus(): ReactNode {
  const { online, syncing, stats, lastSyncAt } = useSession();
  const waiting = stats.pending + stats.syncing;
  const problems = stats.failed + stats.conflict;
  const tone = problems ? colors.danger : online ? colors.primary : colors.offline;
  const lines = [
    syncing ? "Synchronisation…" : online ? "En ligne" : "Hors ligne",
    waiting ? `${waiting} en attente d'envoi` : "",
    problems ? `${problems} à traiter` : "",
  ].filter(Boolean);
  return (
    <Pressable accessibilityRole="button" accessibilityHint="Ouvre l'écran de synchronisation"
               onPress={() => router.push("/sync")}
               style={[styles.card, { borderColor: tone, borderLeftWidth: 6 }]}>
      <Text style={{ fontWeight: "700", color: tone }}>{lines.join(" · ")}</Text>
      <Text style={styles.muted}>
        {!online ? "Vos saisies restent sur le téléphone et partiront au retour du réseau."
          : lastSyncAt ? `Dernière synchronisation ${formatAge(lastSyncAt)}.` : "Synchronisation en cours de démarrage."}
      </Text>
    </Pressable>
  );
}

export default function Home(): ReactNode {
  const { ready, me, farm, pickFarm, can, stats, logout, notice, flash, syncNow, syncing } = useSession();
  const tasks = useLocalEntities<{ id: string; status: string; planned_start_date: string;
                                   planned_end_date: string }>("tasks.task");

  const confirmLogout = () => {
    const unsent = stats.pending + stats.syncing + stats.failed + stats.conflict;
    if (!unsent) return void logout();
    // Sensitive operation: explicit confirmation (CLAUDE.md §7).
    Alert.alert("Se déconnecter ?",
      `Saisies pas encore envoyées : ${unsent}. Elles restent sur ce téléphone et seront envoyées à votre `
      + "prochaine connexion avec ce même compte.", [
        { text: "Annuler", style: "cancel" },
        { text: "Se déconnecter", style: "destructive", onPress: () => void logout() },
      ]);
  };

  if (!ready) return <ActivityIndicator style={{ marginTop: 48 }} color={colors.primary} />;
  if (!me) return <Screen><LoginForm /></Screen>;
  if (!farm) {
    return (
      <Screen>
        <Text style={styles.muted}>Bonjour {me.user.full_name}</Text>
        <Text style={styles.title}>Choisir une exploitation</Text>
        {me.farms.length === 0
          ? <Empty hint="Demandez une invitation à votre administrateur.">Aucune exploitation accessible.</Empty>
          : me.farms.map((f) => (
            <Button key={f.id} variant="secondary" title={f.name} subtitle={roleLabel(f.role) || undefined}
                    onPress={() => pickFarm(f)} />
          ))}
        <Button variant="secondary" title="Déconnexion" onPress={confirmLogout} />
      </Screen>
    );
  }
  const groups = groupTasks(tasks, todayIso());
  const taskSummary = [
    groups.late.length ? `${groups.late.length} en retard` : "",
    groups.today.length ? `${groups.today.length} du jour` : "",
  ].filter(Boolean).join(" · ") || "Rien à faire aujourd'hui";
  const problems = stats.failed + stats.conflict;
  const entries = [
    { title: "Tâches du jour", subtitle: taskSummary, route: "/tasks", visible: can("tasks.view") },
    { title: "Nouvelle observation", route: "/observation", visible: can("observations.create") },
    { title: "Enregistrer une récolte", route: "/harvest", visible: can("harvest.record") },
    { title: "Saisir une dépense", route: "/expense", visible: can("finance.transaction.create") },
  ] as const;
  return (
    <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
      <View>
        <Text style={styles.muted}>Bonjour {me.user.full_name}</Text>
        <Text style={styles.title}>{farm.name}</Text>
      </View>
      <Notice message={notice} onClose={() => flash(null)} />
      <SyncStatus />
      {entries.filter((e) => e.visible).map((e) => (
        <Button key={e.route} title={e.title} subtitle={"subtitle" in e ? e.subtitle : undefined}
                onPress={() => router.push(e.route)} />
      ))}
      <Button variant="secondary" title="Synchronisation" badge={problems} onPress={() => router.push("/sync")} />
      <View style={{ flexDirection: "row", gap: 8 }}>
        {me.farms.length > 1 ? (
          <View style={{ flex: 1 }}>
            <Button variant="secondary" title="Changer d'exploitation" onPress={() => pickFarm(null)} />
          </View>
        ) : null}
        <View style={{ flex: 1 }}>
          <Button variant="secondary" title="Déconnexion" onPress={confirmLogout} />
        </View>
      </View>
    </Screen>
  );
}
