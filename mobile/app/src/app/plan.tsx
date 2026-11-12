/** A validated plan, read-only and offline (S11): key figures from the engine and the calendar. */

import {
  addAmounts, type CalculationLike, engineNumber, formatArea, formatDate, output, PHASE_LABELS, resultsByParcel, todayIso,
} from "@fms/shared";
import { router, useLocalSearchParams } from "expo-router";
import type { ReactNode } from "react";
import { Pressable, Text, View } from "react-native";

import { currentPhase, type Plan, type Version } from "../features/campaigns/model";
import { useLocalEntities, useSession } from "../session/Session";
import { colors, Empty, Screen, SectionTitle, styles } from "../ui/components";

function Figure({ name, value }: { name: string; value: string }): ReactNode {
  return (
    <View style={[styles.card, { flex: 1, minWidth: "45%", gap: 2 }]}>
      <Text style={[styles.muted, { fontSize: 13 }]}>{name}</Text>
      <Text style={{ fontSize: 18, fontWeight: "700", color: colors.text }}>{value}</Text>
    </View>
  );
}

export default function PlanScreen(): ReactNode {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { online } = useSession();
  const plan = useLocalEntities<Plan>("production_plans.plan").find((p) => p._id === id);
  const version = useLocalEntities<Version>("production_plans.plan_version").find((v) => v._id === plan?.current_version);
  if (!plan || !version) return <Screen><Empty>Plan introuvable sur ce téléphone.</Empty></Screen>;

  const results = Object.values(resultsByParcel(version.calculations as unknown as CalculationLike[]));
  const plants = addAmounts(...results.map((r) => output(r.density, "plant_count") ?? "0"));
  const plantable = addAmounts(...results.map((r) => output(r.density, "plantable_area_m2") ?? "0"));
  const area = addAmounts(...version.allocations.map((a) => a.allocated_area_m2));
  const spec = version.planting_spec ?? {};
  const spacing = spec.row_spacing_m && spec.plant_spacing_m
    ? `${engineNumber(String(spec.row_spacing_m))} × ${engineNumber(String(spec.plant_spacing_m))} m` : "—";
  const phases = [...version.phases].sort((a, b) => a.sequence - b.sequence);
  const now = currentPhase(phases);
  const harvest = phases.find((p) => p.phase_code === "harvest");

  return (
    <Screen>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <Text style={[styles.muted, { flexShrink: 1 }]}>
          Version {version.number}{version.validated_at ? `, validée le ${formatDate(version.validated_at.slice(0, 10))}` : ""} ·
          {" "}{plan.variety_name} · {formatArea(area)}
        </Text>
        {!online ? <Text style={[styles.badge, { backgroundColor: "#e7e5e4", color: colors.muted }]}>Hors ligne</Text> : null}
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        <Figure name="Plants prévus" value={engineNumber(plants, 0)} />
        <Figure name="Écartements" value={spacing} />
        <Figure name="Surface plantable" value={formatArea(plantable)} />
        <Figure name="Récolte prévue" value={harvest?.start_date && harvest.end_date
          ? `${formatDate(harvest.start_date).replace(/ \d{4}$/, "")} → ${formatDate(harvest.end_date).replace(/ \d{4}$/, "")}` : "—"} />
      </View>

      <SectionTitle>Calendrier</SectionTitle>
      <View style={styles.card}>
        {phases.map((p, i) => {
          const done = Boolean(p.end_date && p.end_date < todayIso());
          const isNow = now?.phase_code === p.phase_code;
          return (
            <View key={p.phase_code} style={{ flexDirection: "row", gap: 10 }}>
              <View style={{ width: 14, alignItems: "center" }}>
                <View style={{ width: 12, height: 12, borderRadius: 6, marginTop: 4,
                               backgroundColor: isNow ? "#1e40af" : done ? colors.primary : colors.border }} />
                {i < phases.length - 1 ? <View style={{ flex: 1, width: 2, backgroundColor: colors.border }} /> : null}
              </View>
              <View style={{ flex: 1, paddingBottom: 12 }}>
                <Text style={{ fontWeight: isNow ? "700" : "400", color: done ? colors.muted : colors.text }}>
                  {PHASE_LABELS[p.phase_code] ?? p.phase_code}{isNow ? " · en cours" : done ? " · terminée" : ""}
                </Text>
                <Text style={styles.muted}>
                  {p.start_date && p.end_date ? `${formatDate(p.start_date)} → ${formatDate(p.end_date)}` : "Dates non calculées"}
                </Text>
                {isNow ? (
                  <Pressable accessibilityRole="button" onPress={() => router.push("/tasks")} hitSlop={6}>
                    <Text style={styles.link}>Voir les tâches</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
      <Text style={[styles.muted, { textAlign: "center", fontSize: 12 }]}>
        Lecture seule. Les comptes rendus de tâches se saisissent hors ligne et partent au retour du réseau.
      </Text>
    </Screen>
  );
}
