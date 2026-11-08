/**
 * Client-side form validation (CLAUDE.md §7). The server remains the authority:
 * these checks only give immediate feedback, especially offline.
 */

import { CURRENCY_DECIMALS } from "@fms/shared";

export { CURRENCY_DECIMALS };

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

export interface ExpenseForm {
  account: string;
  category: string;
  amount: string;
  business_date: string;
  description: string;
}

export function validateExpense(form: ExpenseForm, currency: string, today: string)
  : Errors<ExpenseForm> {
  const errors: Errors<ExpenseForm> = {};
  if (!form.account) errors.account = "Compte obligatoire.";
  if (!form.category) errors.category = "Catégorie obligatoire.";
  const amount = normalizeDecimal(form.amount);
  const decimals = CURRENCY_DECIMALS[currency];
  if (!DECIMAL.test(amount) || Number(amount) <= 0) {
    errors.amount = "Montant positif obligatoire.";
  } else if (decimals === undefined) {
    errors.amount = `Devise non prise en charge : ${currency}.`;
  } else if ((amount.split(".")[1] ?? "").length > decimals) {
    errors.amount = decimals === 0
      ? `Montant entier en ${currency} (pas de centimes).`
      : `Au plus ${decimals} décimales en ${currency}.`;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.business_date)) {
    errors.business_date = "Date obligatoire.";
  } else if (form.business_date > today) {
    errors.business_date = "La date ne peut pas être dans le futur.";
  }
  return errors;
}

export function hasErrors<T>(errors: Errors<T>): boolean {
  return Object.values(errors).some(Boolean);
}
