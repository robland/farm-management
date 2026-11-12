import { formatAge, groupTasks, organizationGroups, roleLabel, todayIso } from "@fms/shared";
import { NetworkError } from "@fms/sync-core";
import { router } from "expo-router";
import { type ReactNode, useRef, useState } from "react";
import { ActivityIndicator, Pressable, Text, type TextInputInstance, View } from "react-native";

import { useLocalEntities, useSession } from "../session/Session";
import { Button, colors, Empty, Field, PasswordField, Screen, SectionTitle, styles, useBusy } from "../ui/components";

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
             hint="Téléphone avec l'indicatif du pays" />
      <PasswordField ref={passwordRef} label="Mot de passe" value={password} onChangeText={setPassword}
                     autoComplete="current-password" returnKeyType="go" onSubmitEditing={submit} />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Button title={busy ? "Connexion…" : "Se connecter"} busy={busy} onPress={submit} />
    </View>
  );
}

/** Farms grouped by organization; administrators can create a farm in their organization. */
function FarmPicker(): ReactNode {
  const { me, pickFarm } = useSession();
  if (!me) return null;
  const groups = organizationGroups(me);
  return (
    <Screen>
      <Text style={styles.muted}>Bonjour {me.user.full_name}</Text>
      <Text style={styles.title}>Choisir une exploitation</Text>
      {groups.length === 0
        ? <Empty hint="Demandez une invitation à votre administrateur.">Aucune exploitation accessible.</Empty>
        : groups.map((group) => (
          <View key={group.id} style={{ gap: 8 }}>
            <SectionTitle>{group.name}</SectionTitle>
            {group.farms.length === 0
              ? <Text style={styles.muted}>Aucune exploitation dans cette organisation pour le moment.</Text>
              : group.farms.map((f) => (
                <Button key={f.id} variant="secondary" title={f.name}
                        subtitle={(f.is_org_admin && !f.role ? "Administrateur de l'organisation" : roleLabel(f.role))
                          || undefined}
                        onPress={() => pickFarm(f)} />
              ))}
            {group.isAdmin ? (
              <Button variant="secondary" title="+ Créer une exploitation"
                      onPress={() => router.push({ pathname: "/create-farm", params: { org: group.id } })} />
            ) : null}
          </View>
        ))}
    </Screen>
  );
}

/** Coloured connection and queue status; tapping it opens the sync screen. */
function SyncStatus(): ReactNode {
  const { online, syncing, stats, lastSyncAt } = useSession();
  const waiting = stats.pending + stats.syncing;
  const tone = online ? colors.primary : colors.offline;
  const lines = [
    syncing ? "Synchronisation…" : online ? "En ligne" : "Hors ligne",
    waiting ? `${waiting} en attente d'envoi` : "",
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
  const { ready, me, farm, can, syncNow, syncing } = useSession();
  const tasks = useLocalEntities<{ id: string; status: string; planned_start_date: string;
                                   planned_end_date: string }>("tasks.task");

  if (!ready) return <ActivityIndicator style={{ marginTop: 48 }} color={colors.primary} />;
  if (!me) return <Screen><LoginForm /></Screen>;
  if (!farm) return <FarmPicker />;

  const groups = groupTasks(tasks, todayIso());
  const taskSummary = [
    groups.late.length ? `${groups.late.length} en retard` : "",
    groups.today.length ? `${groups.today.length} du jour` : "",
  ].filter(Boolean).join(" · ") || "Rien à faire aujourd'hui";
  const entries = [
    { title: "Tâches du jour", subtitle: taskSummary, route: "/tasks", visible: can("tasks.view") },
    { title: "Campagne", route: "/campaign", visible: can("plans.view") },
    { title: "Nouvelle observation", route: "/observation", visible: can("observations.create") },
    { title: "Enregistrer une récolte", route: "/harvest", visible: can("harvest.record") },
    { title: "Finances", route: "/finance", visible: can("finance.view") || can("finance.transaction.create") },
    // A contributor only has their member account (Q35).
    { title: "Mon compte de membre", route: "/member", visible: can("finance.funding.create") },
  ] as const;
  return (
    <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
      <Text style={styles.title}>{farm.name}</Text>
      <SyncStatus />
      {entries.filter((e) => e.visible).map((e) => (
        <Button key={e.route} title={e.title} subtitle={"subtitle" in e ? e.subtitle : undefined}
                onPress={() => router.push(e.route)} />
      ))}
      <Button variant="secondary" title="Synchronisation" onPress={() => router.push("/sync")} />
    </Screen>
  );
}
