/** Field forms validation (immediate feedback offline; the server stays the authority). */

export { todayIso } from "@fms/shared";

const DECIMAL = /^\d+([.,]\d+)?$/;

export function normalizeDecimal(value: string): string {
  return value.trim().replace(",", ".").replace(/\s/g, "");
}

export function validateQuantity(value: string): string | null {
  const v = normalizeDecimal(value);
  return DECIMAL.test(v) && Number(v) > 0 ? null : "Quantité positive obligatoire.";
}

export function validateSeverity(value: string): string | null {
  if (!value) return null;
  return /^[1-5]$/.test(value) ? null : "Gravité de 1 à 5.";
}
