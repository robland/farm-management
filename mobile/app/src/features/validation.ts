/** Field forms validation (immediate feedback offline; the server stays the authority). */

import { CURRENCY_DECIMALS } from "@fms/shared";

export { todayIso } from "@fms/shared";

const DECIMAL = /^\d+([.,]\d+)?$/;

export function normalizeDecimal(value: string): string {
  return value.trim().replace(",", ".").replace(/\s/g, "");
}

export function validateQuantity(value: string): string | null {
  const v = normalizeDecimal(value);
  return DECIMAL.test(v) && Number(v) > 0 ? null : "Quantité positive obligatoire.";
}

export function validateAmount(value: string, currency: string): string | null {
  const v = normalizeDecimal(value);
  if (!DECIMAL.test(v) || Number(v) <= 0) return "Montant positif obligatoire.";
  const decimals = CURRENCY_DECIMALS[currency];
  if (decimals === undefined) return `Devise non prise en charge : ${currency}.`;
  if ((v.split(".")[1] ?? "").length > decimals) {
    return decimals === 0 ? `Montant entier en ${currency}.` : `Au plus ${decimals} décimales.`;
  }
  return null;
}

export function validateSeverity(value: string): string | null {
  if (!value) return null;
  return /^[1-5]$/.test(value) ? null : "Gravité de 1 à 5.";
}
