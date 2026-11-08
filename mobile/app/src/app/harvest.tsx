import { formatDate, formatNumber } from "@fms/shared";
import * as Crypto from "expo-crypto";
import { router } from "expo-router";
import { type ReactNode, useState } from "react";
import { Text } from "react-native";

import { normalizeDecimal, todayIso, validateQuantity } from "../features/validation";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, Choice, Empty, Field, Screen, styles, useBusy } from "../ui/components";

interface CropCycle { id: string; parcel: string; start_date: string; status: string }
type Grade = "extra" | "grade_1" | "grade_2" | "rejected";

const GRADES: { value: Grade; label: string }[] = [
  { value: "extra", label: "Extra" }, { value: "grade_1", label: "Catégorie I" },
  { value: "grade_2", label: "Catégorie II" }, { value: "rejected", label: "Rebut" },
];
// Mass units only: any other unit needs a measured conversion on the server (FR-091).
const UNITS = ["kg", "g", "t"].map((value) => ({ value, label: value }));

export default function Harvest(): ReactNode {
  const { record, flash, syncNow, syncing } = useSession();
  const cycles = useLocalEntities<CropCycle>("production_plans.crop_cycle")
    .filter((c) => c.status !== "cancelled" && c.status !== "closed");
  const parcels = useLocalEntities<{ id: string; code: string; name: string }>("fields.parcel");
  const [cycle, setCycle] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState("kg");
  const [grade, setGrade] = useState<Grade | null>("grade_1");
  const [losses, setLosses] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [busy, run] = useBusy();
  const selected = cycle ?? (cycles.length === 1 ? cycles[0]?.id ?? null : null);

  const submit = () => void run(async () => {
    const found = { cycle: selected ? null : "Cycle obligatoire.", quantity: validateQuantity(quantity),
                    unit: unit.trim() ? null : "Unité obligatoire.",
                    losses: losses ? validateQuantity(losses) : null };
    setErrors(found);
    if (Object.values(found).some(Boolean) || !selected || !grade) return;
    // Non-mass units are converted on the server with a MEASURED factor only (FR-091).
    await record({
      opType: "create", entityType: "harvest.harvest_record", entityId: Crypto.randomUUID(),
      payload: { crop_cycle: selected, harvested_on: todayIso(), quantity: normalizeDecimal(quantity),
                 unit: unit.trim(), quality_grade: grade,
                 ...(losses ? { loss_quantity_kg: normalizeDecimal(losses) } : {}) },
    });
    flash(`Récolte de ${formatNumber(normalizeDecimal(quantity))} ${unit.trim()} enregistrée sur le téléphone.`);
    router.back();
  });

  if (cycles.length === 0) {
    return (
      <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
        <Empty hint="Les cycles culturaux sont créés depuis les plans de production, puis synchronisés."
               action={{ title: syncing ? "Synchronisation…" : "Synchroniser maintenant", onPress: () => void syncNow() }}>
          Aucun cycle cultural en cours.
        </Empty>
      </Screen>
    );
  }
  const parcelLabel = (id: string) => {
    const p = parcels.find((x) => x.id === id);
    return p ? `${p.code} — ${p.name}` : "Parcelle inconnue";
  };
  return (
    <Screen>
      <Choice label="Cycle cultural" value={selected} onChange={setCycle} error={errors.cycle}
              options={cycles.map((c) => ({ value: c.id,
                                            label: `${parcelLabel(c.parcel)} (depuis le ${formatDate(c.start_date)})` }))} />
      <Field label="Quantité récoltée" value={quantity} onChangeText={setQuantity} keyboardType="decimal-pad"
             error={errors.quantity} />
      <Choice label="Unité" value={UNITS.some((u) => u.value === unit) ? unit : null} onChange={setUnit}
              options={UNITS} />
      <Field label="Autre unité" value={UNITS.some((u) => u.value === unit) ? "" : unit} onChangeText={setUnit}
             autoCapitalize="none" error={errors.unit} placeholder="ex. caisse" />
      <Choice label="Qualité" value={grade} onChange={setGrade} options={GRADES} />
      <Field label="Pertes (kg, facultatif)" value={losses} onChangeText={setLosses} keyboardType="decimal-pad"
             error={errors.losses} />
      <Text style={styles.muted}>
        Récolte datée d'aujourd'hui ({formatDate(todayIso())}). Une unité autre que kg, g ou t doit avoir un
        poids mesuré enregistré sur le serveur.
      </Text>
      <Button title="Enregistrer la récolte" busy={busy} onPress={submit} />
    </Screen>
  );
}
