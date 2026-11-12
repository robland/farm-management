/**
 * Treasury rules shared by the web and mobile clients (FR-070 to FR-077, Q35).
 *
 * Amounts are decimal strings. Sums and differences use exact fixed-point integers
 * (BigInt, 4 decimal places like the server's NUMERIC(19, 4)), never binary floating
 * point (CLAUDE.md §11). The server remains the authority: the checks below only give
 * early feedback, offline included.
 */

import { CURRENCY_DECIMALS } from "./format";

// --- Exact decimal arithmetic --------------------------------------------------------

const SCALE = 4;
const FACTOR = 10n ** BigInt(SCALE);

/**
 * Normalizes an amount received from the API. Serializers send strings ("1500.0000"),
 * but the report endpoints currently send JSON numbers (OPEN_QUESTIONS Q37): a number
 * is converted through its shortest decimal representation, which is exact for the
 * amounts handled here.
 */
export function toAmount(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "0";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "0";
    // toString() may use an exponent for large or tiny values; toFixed avoids it.
    return Math.abs(value) >= 1e21 ? value.toString() : trimZeros(value.toFixed(SCALE));
  }
  return value.trim();
}

function trimZeros(s: string): string {
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}

/** "1 500,5" → 15005000n (scaled by 10⁴); null when not a decimal number. */
export function parseAmount(value: string): bigint | null {
  const cleaned = value.trim().replace(/\s/g, "").replace(",", ".");
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(cleaned);
  if (!match) return null;
  const [, sign, whole = "0", fraction = ""] = match;
  if (fraction.length > SCALE) return null;
  const scaled = BigInt(whole) * FACTOR + BigInt(fraction.padEnd(SCALE, "0") || "0");
  return sign ? -scaled : scaled;
}

/** 15005000n → "1500.5" (no trailing zeros). */
export function amountToString(value: bigint): string {
  const negative = value < 0n;
  const abs = negative ? -value : value;
  const whole = abs / FACTOR;
  const fraction = (abs % FACTOR).toString().padStart(SCALE, "0").replace(/0+$/, "");
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

const scaled = (v: string | number | null | undefined): bigint => parseAmount(toAmount(v)) ?? 0n;

export function addAmounts(...values: (string | number | null | undefined)[]): string {
  return amountToString(values.reduce<bigint>((sum, v) => sum + scaled(v), 0n));
}

export function subtractAmounts(a: string | number, b: string | number): string {
  return amountToString(scaled(a) - scaled(b));
}

export function compareAmounts(a: string | number, b: string | number): -1 | 0 | 1 {
  const d = scaled(a) - scaled(b);
  return d < 0n ? -1 : d > 0n ? 1 : 0;
}

export const isNegative = (a: string | number): boolean => scaled(a) < 0n;
export const isZero = (a: string | number): boolean => scaled(a) === 0n;

/** Explicit sign for flows and variances: "+40000", "-12500", "0". */
export function signed(a: string | number): string {
  const s = amountToString(scaled(a));
  return s.startsWith("-") || s === "0" ? s : `+${s}`;
}

/** part / whole × 100, rounded half away from zero to 2 decimals ("20.00"); null if whole is 0. */
export function percentOf(part: string | number, whole: string | number): string | null {
  const w = scaled(whole);
  if (w === 0n) return null;
  const p = scaled(part);
  const negative = (p < 0n) !== (w < 0n);
  const num = (p < 0n ? -p : p) * 10000n;
  const den = w < 0n ? -w : w;
  const hundredths = (num * 2n + den) / (den * 2n); // rounded
  const text = `${hundredths / 100n}.${(hundredths % 100n).toString().padStart(2, "0")}`;
  return negative && hundredths !== 0n ? `-${text}` : text;
}

/** "-7.61" → "−7,61 %" (typographic minus, decimal comma). */
export function formatPercent(pct: string | null): string {
  if (pct === null) return "—";
  const [whole = "0", frac = "00"] = pct.replace("-", "").split(".");
  const sign = pct.startsWith("-") ? "−" : pct === "0.00" ? "" : "+";
  return `${sign}${whole},${frac} %`;
}

// --- Labels -------------------------------------------------------------------------

export const ACCOUNT_KIND_LABELS: Record<string, string> = {
  cash: "Caisse espèces",
  bank: "Compte bancaire",
  mobile_money: "Mobile money",
  other: "Autre",
};

export const ACCOUNT_ROLE_LABELS: Record<string, string> = {
  main: "Principal",
  member: "Compte de membre",
  operating: "Exploitation",
};

// --- What the user may see and do --------------------------------------------------

export type FinanceView = "overview" | "journal" | "budgets" | "accounts" | "member";

export interface FinanceRights {
  view: boolean;
  create: boolean;
  validate: boolean;
  manageAccounts: boolean;
  fund: boolean;
  editBudget: boolean;
}

export function financeRights(permissions: readonly string[]): FinanceRights {
  const has = (code: string) => permissions.includes(code);
  return {
    view: has("finance.view"),
    create: has("finance.transaction.create"),
    validate: has("finance.transaction.validate"),
    manageAccounts: has("finance.accounts.manage"),
    fund: has("finance.funding.create"),
    editBudget: has("finance.budget.edit"),
  };
}

/**
 * Sub-views of the Finances tab. Without `finance.view`, the server only returns the
 * user's own entries (storekeeper) or their member account (contributor, Q35).
 */
export function financeViews(rights: FinanceRights): FinanceView[] {
  const views: FinanceView[] = [];
  if (rights.view) views.push("overview");
  if (rights.view || rights.create || rights.fund) views.push("journal");
  if (rights.view) views.push("budgets", "accounts");
  if (rights.fund) views.push("member");
  return views;
}

export const FINANCE_VIEW_LABELS: Record<FinanceView, string> = {
  overview: "Vue d'ensemble",
  journal: "Journal",
  budgets: "Budgets",
  accounts: "Comptes et financements",
  member: "Mon compte de membre",
};

// --- Accounts ------------------------------------------------------------------------

export interface AccountLike {
  id: string;
  name: string;
  kind: string;
  role?: string;
  holder?: string | null;
  currency: string;
  is_active: boolean;
}

/** Expenses and incomes never go through a member account (Q35 §4). */
export function entryAccounts<A extends AccountLike>(accounts: A[]): A[] {
  return accounts.filter((a) => a.is_active && a.role !== "member");
}

/** Possible targets of a transfer: same currency, never a member account. */
export function transferTargets<A extends AccountLike>(accounts: A[], fromId: string): A[] {
  const from = accounts.find((a) => a.id === fromId);
  return accounts.filter((a) => a.is_active && a.id !== fromId && a.role !== "member"
    && (!from || a.currency === from.currency));
}

export const mainAccount = <A extends AccountLike>(accounts: A[]): A | undefined =>
  accounts.find((a) => a.role === "main");

// --- Transaction form ------------------------------------------------------------------

/** Kinds a user enters in the general form; fundings are entered from the accounts view. */
export type EntryKind = "expense" | "income" | "transfer" | "repayment" | "funding";

export interface TransactionForm {
  kind: EntryKind;
  account: string;
  to_account: string;
  category: string;
  loan: string;
  amount: string;
  business_date: string;
  description: string;
  campaign: string;
}

export type TransactionErrors = Partial<Record<keyof TransactionForm, string>>;

export const emptyTransactionForm = (kind: EntryKind, today: string): TransactionForm => ({
  kind, account: "", to_account: "", category: "", loan: "", amount: "", business_date: today,
  description: "", campaign: "",
});

/** Positive amount within the currency's minor units ("Montant entier en XAF"). */
export function amountError(amount: string, currency: string): string | undefined {
  const parsed = parseAmount(amount);
  if (parsed === null || parsed <= 0n) return "Montant positif obligatoire.";
  const decimals = CURRENCY_DECIMALS[currency];
  if (decimals === undefined) return `Devise non prise en charge : ${currency}.`;
  const fraction = amount.trim().replace(",", ".").split(".")[1] ?? "";
  if (fraction.replace(/0+$/, "").length > decimals) {
    return decimals === 0 ? `Montant entier en ${currency} (pas de centimes).`
      : `Au plus ${decimals} décimales en ${currency}.`;
  }
  return undefined;
}

export function validateTransaction(form: TransactionForm, accounts: AccountLike[], today: string)
  : TransactionErrors {
  const errors: TransactionErrors = {};
  const account = accounts.find((a) => a.id === form.account);
  if (!account) errors.account = "Compte obligatoire.";
  else if ((form.kind === "expense" || form.kind === "income") && account.role === "member") {
    errors.account = "Un compte de membre ne sert ni aux dépenses ni aux recettes.";
  } else if (form.kind === "repayment" && account.role !== "main") {
    errors.account = "Un remboursement part du compte principal.";
  }
  if ((form.kind === "expense" || form.kind === "income" || form.kind === "funding") && !form.category) {
    errors.category = "Catégorie obligatoire.";
  }
  if (form.kind === "transfer") {
    const target = accounts.find((a) => a.id === form.to_account);
    const fromMember = account?.role === "member";
    if (!target && !fromMember) errors.to_account = "Compte destinataire obligatoire.";
    else if (target && target.id === form.account) errors.to_account = "Identique au compte de départ.";
    else if (target?.role === "member") errors.to_account = "Un compte de membre ne reçoit pas de transfert.";
    else if (target && account && target.currency !== account.currency) {
      errors.to_account = "Les deux comptes doivent avoir la même devise.";
    }
  }
  if (form.kind === "repayment" && !form.loan) errors.loan = "Emprunt obligatoire.";
  const amount = amountError(form.amount, account?.currency ?? "XAF");
  if (amount) errors.amount = amount;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.business_date)) errors.business_date = "Date obligatoire.";
  else if (form.business_date > today) errors.business_date = "La date ne peut pas être dans le futur.";
  return errors;
}

export const hasTransactionErrors = (errors: TransactionErrors): boolean => Object.values(errors).some(Boolean);

/** Body of a creation (REST or sync): only the fields of the chosen kind are sent. */
export function transactionPayload(form: TransactionForm, currency: string): Record<string, unknown> {
  const amount = amountToString(parseAmount(form.amount) ?? 0n);
  const payload: Record<string, unknown> = {
    kind: form.kind, account: form.account, amount, currency, business_date: form.business_date,
    description: form.description.trim(),
  };
  if (form.kind === "transfer") {
    if (form.to_account) payload.to_account = form.to_account;
  } else if (form.kind === "repayment") {
    payload.loan = form.loan;
  } else {
    payload.category = form.category;
    if (form.kind === "funding" && form.loan) payload.loan = form.loan;
  }
  if ((form.kind === "expense" || form.kind === "income") && form.campaign) payload.campaign = form.campaign;
  return payload;
}

// --- Journal -------------------------------------------------------------------------

export interface TransactionLike {
  kind: string;
  status: string;
  amount: string;
  possible_duplicate?: boolean;
  entries?: { account: string; amount: string | number }[];
}

export type Tone = "neutral" | "pending" | "ok" | "danger" | "muted" | "info";

/** Signed amount of a transaction on the farm's books, for display (+ in, − out). */
export function transactionDirection(tx: TransactionLike): "in" | "out" | "move" {
  if (tx.kind === "transfer") return "move";
  if (tx.kind === "income" || tx.kind === "funding") return "in";
  if (tx.kind === "reversal" || tx.kind === "opening") {
    const total = addAmounts(...(tx.entries ?? []).map((e) => e.amount));
    return isNegative(total) ? "out" : "in";
  }
  return "out";
}

/** Status badges of a journal row: workflow status, then warnings. */
export function transactionBadges(tx: TransactionLike): { label: string; tone: Tone }[] {
  const badges: { label: string; tone: Tone }[] = [];
  const status: Record<string, { label: string; tone: Tone }> = {
    submitted: { label: "À valider", tone: "pending" },
    validated: { label: "Validée", tone: "ok" },
    rejected: { label: "Rejetée", tone: "danger" },
    reversed: { label: "Annulée", tone: "muted" },
  };
  const s = status[tx.status];
  if (s) badges.push(s);
  if (tx.possible_duplicate && tx.status === "submitted") badges.push({ label: "Doublon possible", tone: "pending" });
  return badges;
}

/** Only validated expenses and incomes can be corrected; any validated one can be reversed. */
export function transactionActions(tx: TransactionLike, rights: FinanceRights)
  : { validate: boolean; reject: boolean; reverse: boolean; correct: boolean } {
  const submitted = tx.status === "submitted";
  const validated = tx.status === "validated" && tx.kind !== "reversal";
  return {
    validate: rights.validate && submitted,
    reject: rights.validate && submitted,
    reverse: rights.validate && validated,
    correct: rights.validate && validated && (tx.kind === "expense" || tx.kind === "income"),
  };
}

// --- Treasury report (GET transactions/treasury/) ---------------------------------------

type Raw = string | number;

export interface TreasuryPeriod {
  period_start: string;
  inflows: string;
  outflows: string;
  investments: string;
  fundings: string;
  repayments: string;
  transfers: string;
  opening_entries: string;
  net: string;
  closing_balance: string;
}

const FLOW_KEYS = ["inflows", "outflows", "investments", "fundings", "repayments", "transfers",
                   "opening_entries", "net"] as const;

export interface TreasurySummary {
  currency: string;
  opening: string;
  periods: TreasuryPeriod[];
  totals: Record<(typeof FLOW_KEYS)[number], string>;
  closing: string;
  /** Income − campaign expenses: fundings, loans and investments are excluded (Q35). */
  campaignResult: string;
}

export function summarizeTreasury(raw: { currencies?: Record<string, {
  opening_balance: Raw; periods: Record<string, Raw>[] }> }): TreasurySummary[] {
  return Object.entries(raw.currencies ?? {}).map(([currency, data]) => {
    const periods = data.periods.map((p) => {
      const row = { period_start: String(p.period_start ?? "") } as TreasuryPeriod;
      for (const key of [...FLOW_KEYS, "closing_balance"] as const) row[key] = toAmount(p[key]);
      return row;
    });
    const totals = Object.fromEntries(FLOW_KEYS.map((k) => [k, addAmounts(...periods.map((p) => p[k]))])) as
      TreasurySummary["totals"];
    const opening = toAmount(data.opening_balance);
    return {
      currency, opening, periods, totals,
      closing: periods.at(-1)?.closing_balance ?? opening,
      campaignResult: subtractAmounts(totals.inflows, totals.outflows),
    };
  });
}

/**
 * Default report window ending today: 14 days, 8 weeks from a Monday (like the server's
 * buckets) or 6 months from the 1st.
 */
export function treasuryWindow(today: string, period: "day" | "week" | "month"): { from: string; to: string } {
  const [y, m, d] = today.split("-").map(Number) as [number, number, number];
  const date = new Date(Date.UTC(y, m - 1, d));
  const back = period === "day" ? 13 : period === "week" ? 7 * 7 + ((date.getUTCDay() + 6) % 7) : 0;
  if (period === "month") {
    date.setUTCMonth(date.getUTCMonth() - 5, 1);
  } else {
    date.setUTCDate(date.getUTCDate() - back);
  }
  return { from: date.toISOString().slice(0, 10), to: today };
}

// --- Budget report (GET budget-lines/report/) ----------------------------------------

export interface BudgetRow {
  budget_line: string;
  label: string;
  category: string;
  currency: string;
  planned: string;
  actual: string;
  pending: string;
  variance: string;
  variance_pct: string | null;
}

export function normalizeBudgetRows(rows: Record<string, Raw | null>[]): BudgetRow[] {
  return rows.map((r) => ({
    budget_line: String(r.budget_line ?? ""), label: String(r.label ?? ""), category: String(r.category ?? ""),
    currency: String(r.currency ?? ""), planned: toAmount(r.planned), actual: toAmount(r.actual),
    pending: toAmount(r.pending), variance: toAmount(r.variance),
    // Recomputed exactly from the amounts (null when nothing is planned, as on the server).
    variance_pct: percentOf(toAmount(r.variance), toAmount(r.planned)),
  }));
}

/** Totals per currency: never add amounts of different currencies. */
export function budgetTotals(rows: BudgetRow[]): (Omit<BudgetRow, "budget_line" | "label" | "category">)[] {
  const currencies = [...new Set(rows.map((r) => r.currency))];
  return currencies.map((currency) => {
    const own = rows.filter((r) => r.currency === currency);
    const planned = addAmounts(...own.map((r) => r.planned));
    const actual = addAmounts(...own.map((r) => r.actual));
    const variance = subtractAmounts(actual, planned);
    return { currency, planned, actual, pending: addAmounts(...own.map((r) => r.pending)), variance,
             variance_pct: percentOf(variance, planned) };
  });
}

/** Share of the planned amount already spent, capped to 100 for a progress bar. */
export function consumption(row: Pick<BudgetRow, "planned" | "actual" | "pending">)
  : { actual: number; pending: number; over: boolean } {
  const pct = (v: string) => Number(percentOf(v, row.planned) ?? "0");
  const actual = Math.min(100, Math.max(0, pct(row.actual)));
  const pending = Math.min(100 - actual, Math.max(0, pct(row.pending)));
  return { actual, pending, over: compareAmounts(row.actual, row.planned) > 0 };
}
