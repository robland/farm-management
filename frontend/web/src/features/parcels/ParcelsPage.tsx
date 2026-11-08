import { formatArea } from "@fms/shared";
import { type FormEvent, type ReactNode, useState } from "react";

import type { Parcel } from "../../api/types";
import { useLocalEntities, useSync } from "../../sync/SyncContext";
import { Button, Card, EmptyState, Field, Loading, LocalStatus, Notice, SectionHeader, useBusy,
         useNotice } from "../../ui/components";
import { type Errors, hasErrors, normalizeDecimal, type ParcelForm, validateParcel } from "../validation";

const EMPTY: ParcelForm = { name: "", code: "", area_m2: "", soil_ph: "" };

export function ParcelsPage({ canEdit }: { canEdit: boolean }): ReactNode {
  const { record } = useSync();
  const { rows, loading } = useLocalEntities<Parcel>("fields.parcel");
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState<Errors<ParcelForm>>({});
  const [busy, run] = useBusy();
  const [notice, showNotice] = useNotice();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const found = validateParcel(form);
      // Early feedback only: the server enforces uniqueness within the farm (Q15).
      if (!found.code && rows.some((p) => p.code === form.code.trim())) {
        found.code = "Identifiant déjà utilisé dans cette exploitation.";
      }
      setErrors(found);
      if (hasErrors(found)) return;
      // Created locally with a client UUID; works offline (OFFLINE_SYNC.md §3).
      await record({
        opType: "create",
        entityType: "fields.parcel",
        entityId: crypto.randomUUID(),
        payload: {
          name: form.name.trim(),
          code: form.code.trim(),
          area_m2: normalizeDecimal(form.area_m2),
          ...(form.soil_ph.trim() ? { soil_ph: normalizeDecimal(form.soil_ph) } : {}),
        },
      });
      setForm(EMPTY);
      showNotice("Parcelle enregistrée sur cet appareil. Elle sera envoyée dès que possible.");
    });
  };

  const set = (key: keyof ParcelForm) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });
  const sorted = [...rows].sort((a, b) => a.code.localeCompare(b.code, "fr", { numeric: true }));
  const total = rows.reduce((sum, p) => sum + (Number(p.area_m2) || 0), 0);

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader title="Parcelles" count={loading ? undefined : rows.length}>
        {rows.length > 0 && <span className="text-sm text-stone-600">Total : {formatArea(total)}</span>}
      </SectionHeader>
      <Notice message={notice} onClose={() => showNotice(null)} />
      {loading ? <Loading /> : rows.length === 0 ? (
        <EmptyState hint={canEdit ? "Ajoutez la première avec le formulaire ci-dessous." : undefined}>
          Aucune parcelle pour le moment.
        </EmptyState>
      ) : (
        <Card>
          <ul className="divide-y divide-stone-200">
            {sorted.map((parcel) => (
              <li key={parcel._id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                <span className="min-w-0">
                  <strong>{parcel.code}</strong> — {parcel.name}
                  {parcel.soil_ph && <span className="ml-2 text-xs text-stone-500">pH {parcel.soil_ph}</span>}
                </span>
                <span className="flex flex-wrap items-center gap-2 text-sm text-stone-600">
                  {formatArea(parcel.area_m2)}
                  <LocalStatus status={parcel._local} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {canEdit && (
        <Card>
          <form onSubmit={submit} noValidate className="grid gap-3 p-4 sm:grid-cols-2">
            <h3 className="font-medium sm:col-span-2">Nouvelle parcelle</h3>
            <Field label="Nom" value={form.name} onChange={set("name")} error={errors.name} />
            <Field label="Identifiant" value={form.code} onChange={set("code")} error={errors.code}
                   hint="Code court et unique, par exemple P-01." />
            <Field label="Superficie (m²)" inputMode="decimal" value={form.area_m2}
                   onChange={set("area_m2")} error={errors.area_m2} hint="1 ha = 10 000 m²." />
            <Field label="pH du sol (facultatif)" inputMode="decimal" value={form.soil_ph}
                   onChange={set("soil_ph")} error={errors.soil_ph} hint="Valeur mesurée uniquement." />
            <div className="sm:col-span-2">
              <Button type="submit" disabled={busy}>Enregistrer</Button>
            </div>
          </form>
        </Card>
      )}
    </section>
  );
}
