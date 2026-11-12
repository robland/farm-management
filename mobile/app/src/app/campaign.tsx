/**
 * Current campaign on the phone (scenario S11): synced plans, read offline. Designing,
 * computing and validating a plan is done online on the web app (OPEN_QUESTIONS Q7).
 */

import { CAMPAIGN_STATUS_LABELS, formatAge, formatDate, label, PHASE_LABELS, PLAN_STATUS_LABELS } from "@fms/shared";
import { router } from "expo-router";
import { type ReactNode, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { type Campaign, currentPhase, type Plan, type Version } from "../features/campaigns/model";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, Choice, colors, Empty, Screen, styles } from "../ui/components";

export default function CampaignScreen(): ReactNode {
  const { online, lastSyncAt, syncNow, syncing } = useSession();
  const campaigns = useLocalEntities<Campaign>("production_plans.campaign")
    .sort((a, b) => b.start_date.localeCompare(a.start_date));
  const plans = useLocalEntities<Plan>("production_plans.plan");
  const versions = useLocalEntities<Version>("production_plans.plan_version");
  const [picked, setPicked] = useState<string | null>(null);
  const campaign = campaigns.find((c) => c._id === picked) ?? campaigns.find((c) => c.status === "active") ?? campaigns[0];
  const own = plans.filter((p) => p.campaign === campaign?._id).sort((a, b) => a.name.localeCompare(b.name));

  if (!campaign) {
    return (
      <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
        <Empty hint="Les campagnes arrivent avec la synchronisation.">Aucune campagne sur ce téléphone.</Empty>
      </Screen>
    );
  }
  return (
    <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
      {campaigns.length > 1 ? (
        <Choice label="Campagne" value={campaign._id} onChange={setPicked}
                options={campaigns.map((c) => ({ value: c._id, label: c.name }))} />
      ) : null}
      <View>
        <Text style={styles.title}>{campaign.name}</Text>
        <Text style={styles.muted}>
          {label(CAMPAIGN_STATUS_LABELS, campaign.status)} · {formatDate(campaign.start_date)} → {formatDate(campaign.end_date)}
        </Text>
      </View>
      <View style={[styles.card, { borderColor: online ? colors.primary : colors.offline, borderLeftWidth: 6 }]}>
        <Text style={{ fontWeight: "700", color: online ? colors.primary : colors.offline }}>
          {online ? "En ligne" : "Hors ligne"}
        </Text>
        <Text style={styles.muted}>
          {lastSyncAt ? `Plans téléchargés ${formatAge(lastSyncAt)}.` : "Plans de la dernière synchronisation."}
        </Text>
      </View>
      {own.length === 0 ? <Text style={styles.muted}>Aucun plan dans cette campagne.</Text> : own.map((p) => {
        const version = versions.find((v) => v._id === p.current_version);
        const validated = Boolean(version) && p.status !== "draft";
        const phase = version ? currentPhase(version.phases) : undefined;
        return (
          <Pressable key={p._id} accessibilityRole="button" disabled={!validated}
                     accessibilityHint={validated ? "Ouvre le plan" : "Brouillon : à consulter sur l'application Web"}
                     onPress={() => router.push({ pathname: "/plan", params: { id: p._id } })}
                     style={({ pressed }) => [styles.card, { flexDirection: "row", alignItems: "center", gap: 12 },
                                              pressed && styles.pressed]}>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={{ fontSize: 16, fontWeight: "600", color: colors.text }}>{p.name}</Text>
              <Text style={styles.muted}>
                {validated ? (phase ? `${PHASE_LABELS[phase.phase_code] ?? phase.phase_code} · jusqu'au ${formatDate(phase.end_date ?? "")}`
                  : p.variety_name) : "Brouillon, pas encore validé"}
              </Text>
              <Text style={[styles.badge, validated ? { backgroundColor: "#dbeafe", color: "#1e40af" }
                : { backgroundColor: "#f5f5f4", color: colors.muted }]}>{label(PLAN_STATUS_LABELS, p.status)}</Text>
            </View>
            {validated ? <Text style={{ fontSize: 20, color: colors.muted }}>›</Text> : null}
          </Pressable>
        );
      })}
      <Button title="Tâches de la campagne" onPress={() => router.push("/tasks")} />
      <Text style={[styles.muted, { textAlign: "center", fontSize: 12 }]}>
        Concevoir, calculer et valider un plan se fait en ligne, sur l'application Web.
      </Text>
    </Screen>
  );
}
