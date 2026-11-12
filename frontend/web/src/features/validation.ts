/**
 * Client-side form validation (CLAUDE.md §7). The server remains the authority:
 * these checks only give immediate feedback, especially offline.
 */

export type Errors<T> = Partial<Record<keyof T, string>>;

const DECIMAL = /^\d+([.,]\d+)?$/;

export function normalizeDecimal(value: string): string {
  return value.trim().replace(",", ".").replace(/\s/g, "");
}

export interface ParcelForm {
  name: string;
  code: string;
  area_m2: string;
  soil_ph: string;
}

export function validateParcel(form: ParcelForm): Errors<ParcelForm> {
  const errors: Errors<ParcelForm> = {};
  if (!form.name.trim()) errors.name = "Nom obligatoire.";
  if (!form.code.trim()) errors.code = "Identifiant obligatoire.";
  else if (form.code.length > 32) errors.code = "32 caractères au maximum.";
  const area = normalizeDecimal(form.area_m2);
  if (!DECIMAL.test(area) || Number(area) <= 0) {
    errors.area_m2 = "Superficie en m², nombre positif.";
  }
  if (form.soil_ph.trim()) {
    const ph = normalizeDecimal(form.soil_ph);
    if (!DECIMAL.test(ph) || Number(ph) > 14) errors.soil_ph = "pH entre 0 et 14.";
  }
  return errors;
}

export function hasErrors<T>(errors: Errors<T>): boolean {
  return Object.values(errors).some(Boolean);
}
