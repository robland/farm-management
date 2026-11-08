import { CURRENCY_DECIMALS, type FarmForm, farmPayload, validateFarm } from "@fms/shared";
import { NetworkError } from "@fms/sync-core";
import { router, useLocalSearchParams } from "expo-router";
import { type ReactNode, useEffect, useState } from "react";
import { Text } from "react-native";

import { ApiError } from "../api/client";
import { useSession } from "../session/Session";
import { Button, Choice, Empty, Field, Screen, styles, useBusy } from "../ui/components";

interface OrganizationDefaults { country?: string; default_currency?: string; default_timezone?: string }

const CURRENCIES = Object.keys(CURRENCY_DECIMALS).map((c) => ({ value: c, label: c }));

/**
 * Creates a farm in an organization the user administers (org.manage, enforced by the
 * server). Online only: a farm is an organization-level object, not an offline entry.
 */
export default function CreateFarm(): ReactNode {
  const { org } = useLocalSearchParams<{ org: string }>();
  const { api, me, notify, reloadProfile } = useSession();
  const organization = me?.organizations.find((o) => o.id === org && o.is_org_admin);
  const [form, setForm] = useState<FarmForm>({
    name: "", code: "", country: "", currency: "", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
  });
  const [errors, setErrors] = useState<Partial<Record<keyof FarmForm, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();

  useEffect(() => {
    if (!organization) return;
    // Prefill with the organization defaults when reachable; never overwrite typed values.
    api.request<OrganizationDefaults>("GET", `/organizations/${organization.id}/`)
      .then((o) => setForm((f) => ({ ...f, country: f.country || o.country || "",
                                     currency: f.currency || o.default_currency || "",
                                     timezone: o.default_timezone || f.timezone })))
      .catch(() => undefined);
  }, [api, organization?.id]);

  if (!organization) return <Empty>Seuls les administrateurs de l'organisation peuvent créer une exploitation.</Empty>;

  const set = (key: keyof FarmForm) => (value: string) => setForm({ ...form, [key]: value });

  const submit = () => void run(async () => {
    const found = validateFarm(form);
    setErrors(found);
    if (Object.values(found).some(Boolean)) return;
    setError(null);
    try {
      await api.request("POST", `/organizations/${organization.id}/farms/`, farmPayload(form));
      await reloadProfile();
      notify({ type: "success", farmId: null, text: `Exploitation « ${form.name.trim()} » créée.` });
      router.back();
    } catch (err) {
      if (err instanceof NetworkError) {
        setError("Création impossible hors ligne : une exploitation se crée avec le réseau.");
      } else if (err instanceof ApiError) {
        setError(err.status === 403 ? "Vous n'êtes pas administrateur de cette organisation."
          : err.body.message || "Création refusée par le serveur.");
      } else {
        throw err;
      }
    }
  });

  return (
    <Screen>
      <Text style={styles.muted}>{organization.name}</Text>
      <Field label="Nom" value={form.name} onChangeText={set("name")} error={errors.name} />
      <Field label="Code" value={form.code} onChangeText={set("code")} error={errors.code} autoCapitalize="none"
             autoCorrect={false} hint="Court et unique dans l'organisation, ex. ferme-nord." />
      <Field label="Pays" value={form.country} onChangeText={set("country")} error={errors.country}
             autoCapitalize="characters" maxLength={2} hint="Code à 2 lettres, ex. CM." />
      <Choice label="Devise" value={form.currency || null} onChange={set("currency")} options={CURRENCIES}
              error={errors.currency} />
      <Field label="Fuseau horaire" value={form.timezone} onChangeText={set("timezone")} error={errors.timezone}
             autoCapitalize="none" autoCorrect={false} hint="Format IANA, ex. Africa/Douala." />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Button title={busy ? "Création…" : "Créer l'exploitation"} busy={busy} onPress={submit} />
    </Screen>
  );
}
