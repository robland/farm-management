import { OBSERVATION_KIND_LABELS } from "@fms/shared";
import * as Crypto from "expo-crypto";
import { router } from "expo-router";
import { type ReactNode, useState } from "react";
import { Text } from "react-native";

import { validateSeverity } from "../features/validation";
import { useLocalEntities, useSession } from "../session/Session";
import { Button, Choice, Empty, Field, Screen, styles, useBusy } from "../ui/components";

interface Parcel { id: string; code: string; name: string }
type Kind = "pest" | "disease" | "growth" | "weather" | "water" | "other";

const KINDS = (Object.keys(OBSERVATION_KIND_LABELS) as Kind[])
  .map((value) => ({ value, label: OBSERVATION_KIND_LABELS[value] ?? value }));
const SEVERITIES = ["1", "2", "3", "4", "5"].map((value) => ({ value, label: value }));

export default function Observation(): ReactNode {
  const { record, flash, syncNow, syncing } = useSession();
  const parcels = useLocalEntities<Parcel>("fields.parcel");
  const [parcel, setParcel] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind | null>(null);
  const [target, setTarget] = useState("");
  const [severity, setSeverity] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [busy, run] = useBusy();
  // One parcel: nothing to choose.
  const selected = parcel ?? (parcels.length === 1 ? parcels[0]?.id ?? null : null);

  const submit = () => void run(async () => {
    const found = { parcel: selected ? null : "Parcelle obligatoire.", kind: kind ? null : "Type obligatoire.",
                    severity: validateSeverity(severity ?? "") };
    setErrors(found);
    if (Object.values(found).some(Boolean) || !selected || !kind) return;
    await record({
      opType: "create", entityType: "agronomy.observation", entityId: Crypto.randomUUID(),
      payload: { parcel: selected, kind, target: target.trim(), notes: notes.trim(),
                 observed_at: new Date().toISOString(), ...(severity ? { severity: Number(severity) } : {}) },
    });
    flash("Observation enregistrée sur le téléphone. Elle sera envoyée dès que possible.");
    router.back();
  });

  if (parcels.length === 0) {
    return (
      <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
        <Empty hint="Les parcelles arrivent avec la synchronisation."
               action={{ title: syncing ? "Synchronisation…" : "Synchroniser maintenant", onPress: () => void syncNow() }}>
          Aucune parcelle sur ce téléphone.
        </Empty>
      </Screen>
    );
  }
  return (
    <Screen>
      <Choice label="Parcelle" value={selected} onChange={setParcel} error={errors.parcel}
              options={parcels.map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />
      <Choice label="Type" value={kind} onChange={setKind} options={KINDS} error={errors.kind} />
      <Field label="Cible (ravageur, maladie…)" value={target} onChangeText={setTarget} />
      <Choice label="Gravité (1 faible à 5 forte, facultatif)" value={severity} onChange={setSeverity}
              options={SEVERITIES} error={errors.severity} />
      <Field label="Notes" value={notes} onChangeText={setNotes} multiline />
      <Text style={styles.muted}>Enregistrée sur le téléphone, envoyée dès que le réseau revient.</Text>
      <Button title="Enregistrer l'observation" busy={busy} onPress={submit} />
    </Screen>
  );
}
