/** Farm picker and farm creation rules shared by the web and mobile clients. */

export interface FarmForm {
  name: string;
  code: string;
  country: string;
  timezone: string;
  currency: string;
}

const SLUG = /^[-a-zA-Z0-9_]+$/;

/** Early feedback only: the server validates the farm and enforces org.manage. */
export function validateFarm(form: FarmForm): Partial<Record<keyof FarmForm, string>> {
  const errors: Partial<Record<keyof FarmForm, string>> = {};
  if (!form.name.trim()) errors.name = "Nom obligatoire.";
  if (!form.code.trim()) errors.code = "Code obligatoire.";
  else if (form.code.trim().length > 32) errors.code = "32 caractères au maximum.";
  else if (!SLUG.test(form.code.trim())) errors.code = "Lettres sans accent, chiffres, - et _ uniquement.";
  if (!/^[A-Za-z]{2}$/.test(form.country.trim())) errors.country = "Code pays à 2 lettres (ISO 3166), ex. CM.";
  if (!form.timezone.trim()) errors.timezone = "Fuseau horaire obligatoire.";
  if (!form.currency) errors.currency = "Devise obligatoire.";
  return errors;
}

/** Request body of POST /organizations/{id}/farms/. */
export function farmPayload(form: FarmForm): FarmForm {
  return { name: form.name.trim(), code: form.code.trim(), country: form.country.trim().toUpperCase(),
           timezone: form.timezone.trim(), currency: form.currency };
}

interface MeLike<F> {
  organizations: { id: string; name: string; is_org_admin: boolean }[];
  farms: F[];
}

/** Organizations to list: those with a farm, plus those the user administers (to create one). */
export function organizationGroups<F extends { organization_id: string }>(me: MeLike<F>)
  : { id: string; name: string; isAdmin: boolean; farms: F[] }[] {
  const ids = new Set([...me.farms.map((f) => f.organization_id),
                       ...me.organizations.filter((o) => o.is_org_admin).map((o) => o.id)]);
  return [...ids].map((id) => {
    const org = me.organizations.find((o) => o.id === id);
    return { id, name: org?.name ?? "Organisation", isAdmin: Boolean(org?.is_org_admin),
             farms: me.farms.filter((f) => f.organization_id === id) };
  });
}

/** "Awa Diallo" → "AD"; one word → its first letter. */
export function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts;
  return letters.map((p) => p?.[0] ?? "").join("").toUpperCase() || "?";
}
