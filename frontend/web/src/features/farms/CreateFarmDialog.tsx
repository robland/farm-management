import { CURRENCY_DECIMALS } from "@fms/shared";
import { NetworkError } from "@fms/sync-core";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { ApiError, type ApiClient } from "../../api/client";
import { Button, ErrorMessage, Field, Select, useBusy } from "../../ui/components";
import { type Errors, hasErrors } from "../validation";

export interface FarmForm {
  name: string;
  code: string;
  country: string;
  timezone: string;
  currency: string;
}

const SLUG = /^[-a-zA-Z0-9_]+$/;

/** Early feedback only: the server validates and enforces org.manage. */
export function validateFarm(form: FarmForm): Errors<FarmForm> {
  const errors: Errors<FarmForm> = {};
  if (!form.name.trim()) errors.name = "Nom obligatoire.";
  if (!form.code.trim()) errors.code = "Code obligatoire.";
  else if (form.code.trim().length > 32) errors.code = "32 caractères au maximum.";
  else if (!SLUG.test(form.code.trim())) errors.code = "Lettres sans accent, chiffres, - et _ uniquement.";
  if (!/^[A-Za-z]{2}$/.test(form.country.trim())) errors.country = "Code pays à 2 lettres (ISO 3166), ex. CM.";
  if (!form.timezone.trim()) errors.timezone = "Fuseau horaire obligatoire.";
  if (!form.currency) errors.currency = "Devise obligatoire.";
  return errors;
}

interface OrganizationDefaults { country?: string; default_currency?: string; default_timezone?: string }

/**
 * Creates a farm in an organization the user administers. Online only: a farm is an
 * organization-level object, not a field entry of the offline queue.
 */
export function CreateFarmDialog(props: { api: ApiClient; organization: { id: string; name: string };
                                          onCancel: () => void; onCreated: (name: string) => void }): ReactNode {
  const { api, organization } = props;
  const [form, setForm] = useState<FarmForm>({
    name: "", code: "", country: "", currency: "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
  });
  const [errors, setErrors] = useState<Errors<FarmForm>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();

  useEffect(() => {
    // Prefill with the organization defaults when reachable; never overwrite typed values.
    api.request<OrganizationDefaults>("GET", `/organizations/${organization.id}/`)
      .then((org) => setForm((f) => ({
        ...f,
        country: f.country || org.country || "",
        currency: f.currency || org.default_currency || "",
        timezone: org.default_timezone || f.timezone,
      })))
      .catch(() => undefined);
  }, [api, organization.id]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const found = validateFarm(form);
      setErrors(found);
      if (hasErrors(found)) return;
      setError(null);
      try {
        await api.request("POST", `/organizations/${organization.id}/farms/`, {
          name: form.name.trim(), code: form.code.trim(), country: form.country.trim().toUpperCase(),
          timezone: form.timezone.trim(), currency: form.currency,
        });
        props.onCreated(form.name.trim());
      } catch (err) {
        if (err instanceof NetworkError) {
          setError("Création impossible hors ligne : une exploitation se crée avec le réseau.");
        } else if (err instanceof ApiError) {
          const fields = err.body.field_errors ?? {};
          const first = (key: keyof FarmForm) => {
            const value = fields[key];
            return Array.isArray(value) && typeof value[0] === "string" ? value[0] : undefined;
          };
          setErrors({ name: first("name"), code: first("code"), country: first("country"),
                      timezone: first("timezone"), currency: first("currency") });
          setError(err.status === 403 ? "Vous n'êtes pas administrateur de cette organisation."
            : err.body.message || "Création refusée par le serveur.");
        } else {
          throw err;
        }
      }
    });
  };

  const set = (key: keyof FarmForm) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center"
         onClick={(event) => event.target === event.currentTarget && props.onCancel()}>
      <div role="dialog" aria-modal="true" aria-labelledby="create-farm-title"
           className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-4 shadow-lg"
           onKeyDown={(event) => event.key === "Escape" && props.onCancel()}>
        <h2 id="create-farm-title" className="font-semibold">Créer une exploitation</h2>
        <p className="mb-3 text-sm text-stone-600">{organization.name}</p>
        <form onSubmit={submit} noValidate className="flex flex-col gap-3">
          <Field label="Nom" value={form.name} onChange={set("name")} error={errors.name} autoFocus />
          <Field label="Code" value={form.code} onChange={set("code")} error={errors.code}
                 hint="Court et unique dans l'organisation, ex. ferme-nord." />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Pays" value={form.country} onChange={set("country")} error={errors.country}
                   maxLength={2} hint="Code à 2 lettres, ex. CM." />
            <Select label="Devise" value={form.currency} onChange={set("currency")} error={errors.currency}
                    options={Object.keys(CURRENCY_DECIMALS).map((c) => ({ value: c, label: c }))} />
          </div>
          <Field label="Fuseau horaire" value={form.timezone} onChange={set("timezone")} error={errors.timezone}
                 hint="Format IANA, ex. Africa/Douala." />
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <div className="mt-1 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={props.onCancel}>Annuler</Button>
            <Button type="submit" disabled={busy}>{busy ? "Création…" : "Créer l'exploitation"}</Button>
          </div>
        </form>
      </div>
    </div>
  );
}
