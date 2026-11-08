/**
 * Display formatting (French locale), shared by the web and mobile clients.
 *
 * Amounts stay decimal strings end to end: they are formatted by string manipulation,
 * never through binary floating point (CLAUDE.md §11). Formatting is deterministic and
 * does not depend on the platform's Intl data (Hermes and browsers differ).
 */

/** Narrow no-break space: French thousands separator. */
const GROUP = " ";

/** ISO 4217 minor units of the currencies used by the farms (backend apps/core/money.py). */
export const CURRENCY_DECIMALS: Record<string, number> = {
  XAF: 0, XOF: 0, CDF: 2, EUR: 2, USD: 2,
};

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
                "nov.", "déc."];

function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP);
}

/**
 * "15000" XAF → "15 000 XAF"; "1234.5" EUR → "1 234,50 EUR".
 * An unparseable amount is returned unchanged rather than hidden.
 */
export function formatMoney(amount: string, currency: string): string {
  const match = /^(-?)(\d+)(?:[.,](\d+))?$/.exec(amount.trim());
  if (!match) return `${amount} ${currency}`;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const decimals = CURRENCY_DECIMALS[currency];
  let frac = fraction;
  if (decimals !== undefined) {
    // Pad only: the server already enforces the currency precision, so never round here.
    frac = fraction.length < decimals ? fraction.padEnd(decimals, "0") : fraction;
    if (decimals === 0 && /^0*$/.test(frac)) frac = "";
  }
  const body = groupDigits(whole.replace(/^0+(?=\d)/, ""));
  return `${sign}${body}${frac ? `,${frac}` : ""} ${currency}`;
}

/** Plain number with French grouping and decimal comma ("2500.75" → "2 500,75"). */
export function formatNumber(value: string | number, maxDecimals = 2): string {
  const n = typeof value === "number" ? value : Number(String(value).replace(",", "."));
  if (!Number.isFinite(n)) return String(value);
  const fixed = Math.abs(n).toFixed(maxDecimals).replace(/\.?0+$/, "");
  const [whole = "0", fraction] = fixed.split(".");
  return `${n < 0 ? "-" : ""}${groupDigits(whole)}${fraction ? `,${fraction}` : ""}`;
}

/** Surface in m², with the hectare equivalent from 1 000 m² (1 ha = 10 000 m²). */
export function formatArea(areaM2: string | number): string {
  const n = typeof areaM2 === "number" ? areaM2 : Number(String(areaM2).replace(",", "."));
  if (!Number.isFinite(n)) return `${areaM2} m²`;
  const m2 = `${formatNumber(n)} m²`;
  return n >= 1000 ? `${m2} (${formatNumber(n / 10_000, 2)} ha)` : m2;
}

/** "2026-11-08" → "8 nov. 2026". Calendar dates have no time zone: no Date parsing. */
export function formatDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return isoDate;
  const [, year, month, day] = match;
  const name = MONTHS[Number(month) - 1];
  return name ? `${Number(day)} ${name} ${year}` : isoDate;
}

/** Date range of a task: "8 nov. 2026" or "8 nov. 2026 → 12 nov. 2026". */
export function formatDateRange(start: string, end: string): string {
  return start === end ? formatDate(start) : `${formatDate(start)} → ${formatDate(end)}`;
}

/** Local date and time of an instant: "8 nov. 2026 à 14:05". */
export function formatDateTime(value: string | Date): string {
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return String(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = formatDate(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`);
  return `${date} à ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Today's calendar date in the device time zone (toISOString() would give the UTC date). */
export function todayIso(now = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** "il y a 3 min" style age of the last synchronization. */
export function formatAge(from: Date, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - from.getTime()) / 1000));
  if (seconds < 60) return "à l'instant";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `le ${formatDateTime(from)}`;
}
