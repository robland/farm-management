/**
 * Production planning rules shared by the web and mobile clients (FR-030 to FR-035,
 * docs/functional/PLANNING_SCENARIOS.md). No agronomic value is produced here: values come
 * from the user, the validated technical data or the server's deterministic engine.
 */

import { addAmounts, amountToString, compareAmounts, parseAmount, subtractAmounts } from "./finance";
import { formatNumber } from "./format";

export const CAMPAIGN_STATUS_LABELS: Record<string, string> = {
  planned: "Planifiée", active: "En cours", closed: "Clôturée",
};

export const PLAN_STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon", validated: "Validé", in_progress: "En exécution", closed: "Clôturé", cancelled: "Annulé",
};

export const VERSION_STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon", validated: "Validée", superseded: "Remplacée", rejected: "Rejetée",
};

export const VERSION_ORIGIN_LABELS: Record<string, string> = {
  manual: "Saisie manuelle", ai_draft: "Brouillon assisté par l'IA", copy: "Copie d'une version",
};

export const CYCLE_STATUS_LABELS: Record<string, string> = {
  planned: "Planifié", active: "En cours", harvested: "Récolté", closed: "Clôturé", cancelled: "Annulé",
};

/** Default phase codes (backend apps/varieties/technical_keys.py); others are shown as-is. */
export const PHASE_LABELS: Record<string, string> = {
  soil_preparation: "Préparation du sol",
  sowing: "Semis",
  nursery: "Pépinière",
  transplanting: "Repiquage",
  vegetative: "Croissance végétative",
  flowering: "Floraison",
  fruiting: "Fructification",
  maturation: "Maturation",
  harvest: "Récolte",
};

export const SOURCE_KIND_LABELS: Record<string, string> = {
  document: "Source documentaire",
  calculation: "Calcul déterministe",
  ai_suggestion: "Recommandation IA",
  user_input: "Saisie utilisateur",
};

export const PLANTING_METHOD_LABELS: Record<string, string> = {
  direct_seeding: "Semis direct", transplanting: "Repiquage",
};

export const LAYOUT_LABELS: Record<string, string> = { single_row: "Lignes simples", beds: "Planches" };

export type PlantingFieldKind = "decimal" | "integer" | "percent" | "choice";

export interface PlantingFieldSpec {
  key: string;
  label: string;
  unit: string;
  kind: PlantingFieldKind;
  /** Shown only for this planting method or layout. */
  method?: string;
  layout?: string;
}

/** Fields of the planting parameters (backend PLANTING_FIELDS), in the order of the form. */
export const PLANTING_FIELDS: PlantingFieldSpec[] = [
  { key: "planting_method", label: "Méthode", unit: "", kind: "choice" },
  { key: "layout", label: "Disposition", unit: "", kind: "choice" },
  { key: "row_spacing_m", label: "Écartement entre lignes", unit: "m", kind: "decimal" },
  { key: "plant_spacing_m", label: "Écartement entre plants", unit: "m", kind: "decimal" },
  { key: "plants_per_hole", label: "Plants par trou", unit: "", kind: "integer" },
  { key: "seeds_per_hole", label: "Graines par trou", unit: "", kind: "integer" },
  { key: "headland_m", label: "Bordure non plantée", unit: "m", kind: "decimal" },
  { key: "bed_width_m", label: "Largeur de planche", unit: "m", kind: "decimal", layout: "beds" },
  { key: "path_width_m", label: "Largeur d'allée", unit: "m", kind: "decimal", layout: "beds" },
  { key: "rows_per_bed", label: "Lignes par planche", unit: "", kind: "integer", layout: "beds" },
  { key: "germination_rate", label: "Taux de germination", unit: "%", kind: "percent" },
  { key: "nursery_success_rate", label: "Réussite en pépinière", unit: "%", kind: "percent", method: "transplanting" },
  { key: "safety_margin_rate", label: "Marge de sécurité", unit: "%", kind: "percent" },
  { key: "seeds_per_gram", label: "Graines par gramme", unit: "", kind: "decimal" },
  { key: "thousand_seed_weight_g", label: "Poids de mille graines", unit: "g", kind: "decimal" },
  { key: "seed_package_size_g", label: "Taille du sachet", unit: "g", kind: "decimal" },
];

const HEADER_LABELS: Record<string, string> = {
  planned_start_date: "Date de début", planned_end_date: "Date de fin", target_yield_kg_per_ha: "Rendement visé",
  objectives: "Objectifs", constraints_notes: "Contraintes", change_note: "Note de changement",
  allocations: "Parcelles", phases: "Phases du calendrier", start_date: "Date de début",
  allocated_area_m2: "Surface allouée", non_plantable_area_m2: "Surface non plantable",
  plot_length_m: "Longueur de la parcelle", plot_width_m: "Largeur de la parcelle",
  plant_count: "Nombre de plants", seed_count: "Graines nécessaires", technical_data: "Données techniques validées",
};

/** "planting_spec.row_spacing_m" → "Écartement entre lignes"; "phases.nursery.duration_days" → "Durée : Pépinière". */
export function fieldLabel(path: string): string {
  const parts = path.split(".");
  if (parts[0] === "phases" && parts.length >= 2) return `Durée : ${PHASE_LABELS[parts[1] ?? ""] ?? parts[1]}`;
  const key = parts[0] === "planting_spec" || parts[0] === "header" ? parts.slice(1).join(".") : path;
  return PLANTING_FIELDS.find((f) => f.key === key)?.label ?? HEADER_LABELS[key] ?? key;
}

// --- Rates: the server stores ratios (0.75), the forms show percentages (75) -------------

/** "0.75" → "75"; null or invalid → "". Exact: decimal strings, never floats. */
export function ratioToPercent(ratio: string | number | null | undefined): string {
  if (ratio === null || ratio === undefined || ratio === "") return "";
  const scaled = parseAmount(String(ratio));
  return scaled === null ? "" : amountToString(scaled * 100n);
}

/**
 * "75" or "75,5" → "0.75" / "0.755"; empty → null; invalid → undefined. A percentage
 * needing more than the 4 decimals stored by the server (e.g. 75,123 %) is refused.
 */
export function percentToRatio(percent: string): string | null | undefined {
  if (!percent.trim()) return null;
  const scaled = parseAmount(percent);
  if (scaled === null || scaled < 0n || scaled % 100n !== 0n) return undefined;
  return amountToString(scaled / 100n);
}

// --- Rights and actions -------------------------------------------------------------

export interface PlanRights {
  view: boolean;
  edit: boolean;
  validate: boolean;
  ai: boolean;
  generateTasks: boolean;
}

export function planRights(permissions: readonly string[]): PlanRights {
  const has = (code: string) => permissions.includes(code);
  return { view: has("plans.view"), edit: has("plans.edit"), validate: has("plans.validate"), ai: has("ai.use"),
           generateTasks: has("tasks.edit") };
}

export interface VersionLike { status: string; number?: number }

/**
 * What may be done on a version (PLANNING_SCENARIOS.md): a validated version is frozen;
 * validation needs a complete calculation and no AI suggestion left undecided.
 */
export function versionActions(version: VersionLike, rights: PlanRights, state: {
  complete: boolean | null; pendingSuggestions: number; hasDraft: boolean; planClosed: boolean }) {
  const draft = version.status === "draft";
  let blocked: string | null = null;
  if (draft) {
    if (state.pendingSuggestions > 0) {
      blocked = `${state.pendingSuggestions} suggestion${state.pendingSuggestions > 1 ? "s" : ""} IA à accepter, modifier ou rejeter.`;
    } else if (state.complete === null) blocked = "Lancez le calcul avant de valider.";
    else if (!state.complete) blocked = "Le plan est incomplet : voir « À compléter ».";
    else if (state.planClosed) blocked = "Le plan est clôturé ou annulé.";
  }
  return {
    edit: draft && rights.edit,
    compute: draft && rights.edit,
    validate: draft && rights.validate,
    validateBlocked: blocked,
    newVersion: version.status === "validated" && rights.edit && !state.hasDraft && !state.planClosed,
    generateTasks: version.status === "validated" && rights.generateTasks,
  };
}

// --- "À compléter": the calculation's missing data, as a to-do list (scenario S3) --------

export type PlanSection = "header" | "parcels" | "planting" | "calendar";

export interface MissingEntry { scope: string; fields?: string[]; field?: string; reason?: string }

const PARCEL_FIELDS = new Set(["allocations", "allocated_area_m2", "non_plantable_area_m2", "plot_length_m",
                               "plot_width_m"]);

export function missingItems(missing: MissingEntry[], parcelName: (id: string) => string)
  : { key: string; where: string; what: string; section: PlanSection; reason: string }[] {
  return missing.flatMap((m) => (m.fields ?? (m.field ? [m.field] : [])).map((field) => {
    const parcel = m.scope.startsWith("parcel:") ? m.scope.slice("parcel:".length) : null;
    const section: PlanSection = m.scope === "calendar" ? "calendar"
      : PARCEL_FIELDS.has(field) ? "parcels" : field in HEADER_LABELS && !parcel ? "header" : "planting";
    const where = parcel ? parcelName(parcel) : m.scope === "calendar" ? "Calendrier" : "Plan";
    return { key: `${m.scope}:${field}`, where, what: fieldLabel(field), section, reason: m.reason ?? "" };
  }));
}

// --- Results of the engine (CalculationRecord) -------------------------------------------

export interface CalculationLike {
  calc_type: string;
  scope: string;
  engine_version?: string;
  inputs: Record<string, { value: unknown; unit: string }>;
  outputs: Record<string, { value: unknown; unit: string }>;
  formula: string;
  assumptions: string[];
  warnings: string[];
  details: Record<string, unknown>;
  created_at?: string;
}

export const output = (calc: CalculationLike | undefined, name: string): string | undefined => {
  const value = calc?.outputs[name]?.value;
  return value === undefined || value === null ? undefined : String(value);
};

/** Density and seed calculations per parcel id. */
export function resultsByParcel(calculations: CalculationLike[])
  : Record<string, { density?: CalculationLike; seeds?: CalculationLike }> {
  const out: Record<string, { density?: CalculationLike; seeds?: CalculationLike }> = {};
  for (const calc of calculations) {
    if (!calc.scope.startsWith("parcel:")) continue;
    const id = calc.scope.slice("parcel:".length);
    const entry = (out[id] ??= {});
    if (calc.calc_type === "planting.density") entry.density = calc;
    if (calc.calc_type === "planting.seeds") entry.seeds = calc;
  }
  return out;
}

/** Relative gap between real and theoretical plant counts, in % with one decimal ("+7,0 %"). */
export function plantGap(density: CalculationLike | undefined): string | null {
  const real = output(density, "plant_count");
  const theoretical = output(density, "theoretical_plant_count");
  if (!real || !theoretical || theoretical === "0") return null;
  const r = BigInt(real);
  const t = BigInt(theoretical);
  const tenths = ((r - t) * 2000n + (r >= t ? t : -t)) / (2n * t); // rounded, in tenths of %
  const abs = tenths < 0n ? -tenths : tenths;
  return `${tenths < 0n ? "−" : "+"}${abs / 10n},${abs % 10n} %`;
}

/** Engine values are decimal strings: "1.9800" → "1,98". */
export const engineNumber = (value: string | undefined, maxDecimals = 2): string =>
  value === undefined ? "—" : formatNumber(value, maxDecimals);

// --- Parcel occupation (scenario S5) ----------------------------------------------------

export interface CycleLike {
  plan: string;
  parcel: string;
  area_m2: string | number;
  start_date: string;
  end_date: string;
  status: string;
}

const overlaps = (a: { start: string; end: string }, b: { start: string; end: string }) =>
  a.start <= b.end && b.start <= a.end;

/**
 * Area already reserved on a parcel by other plans over a period, and what is left. The
 * server checks again at validation; this only warns while the plan is being prepared.
 */
export function parcelAvailability(parcelAreaM2: string, cycles: CycleLike[], parcel: string,
                                   period: { start: string; end: string }, planId: string)
  : { occupied: string; available: string } {
  const occupied = addAmounts(...cycles.filter((c) => c.parcel === parcel && c.plan !== planId
    && c.status !== "cancelled" && overlaps({ start: c.start_date, end: c.end_date }, period)).map((c) => c.area_m2));
  const left = subtractAmounts(parcelAreaM2, occupied);
  return { occupied, available: compareAmounts(left, 0) < 0 ? "0" : left };
}

// --- Timeline (campaign view) -----------------------------------------------------------

const dayNumber = (iso: string): number => {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  return Date.UTC(y, m - 1, d) / 86_400_000;
};

/** Position of [start, end] inside the window, in % (clipped); null when outside. */
export function timelineBar(window: { start: string; end: string }, start: string, end: string)
  : { left: number; width: number } | null {
  const w0 = dayNumber(window.start);
  const span = dayNumber(window.end) - w0 + 1;
  const s = Math.max(dayNumber(start), w0);
  const e = Math.min(dayNumber(end), dayNumber(window.end));
  if (span <= 0 || e < s) return null;
  return { left: ((s - w0) / span) * 100, width: ((e - s + 1) / span) * 100 };
}

const MONTHS = ["Janv.", "Févr.", "Mars", "Avr.", "Mai", "Juin", "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc."];

/** Month columns covering a window: [{label: "Oct.", start: "2026-10-01"}…]. */
export function monthColumns(window: { start: string; end: string }): { label: string; start: string }[] {
  const columns: { label: string; start: string }[] = [];
  let [y, m] = window.start.split("-").map(Number) as [number, number];
  const [ey, em] = window.end.split("-").map(Number) as [number, number];
  while (y < ey || (y === ey && m <= em)) {
    columns.push({ label: MONTHS[m - 1] ?? String(m), start: `${y}-${String(m).padStart(2, "0")}-01` });
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return columns;
}

// --- Version comparison (GET plans/{id}/compare/) -----------------------------------------

const SECTION_LABELS: Record<string, string> = {
  header: "En-tête", planting_spec: "Paramètres", allocations: "Parcelles", phases: "Calendrier", results: "Résultats",
};

export function comparisonRows(differences: { section: string; field: string; from: unknown; to: unknown }[],
                               parcelName: (id: string) => string)
  : { section: string; field: string; from: string; to: string }[] {
  const show = (field: string, value: unknown): string => {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") {
      return Object.entries(value as Record<string, unknown>)
        .map(([k, v]) => `${fieldLabel(k)} ${show(k, v)}`).join(", ");
    }
    if (field.endsWith("_rate")) return `${ratioToPercent(String(value))} %`;
    const text = String(value);
    if (PLANTING_METHOD_LABELS[text]) return PLANTING_METHOD_LABELS[text] ?? text;
    if (LAYOUT_LABELS[text]) return LAYOUT_LABELS[text] ?? text;
    return /^-?\d+(\.\d+)?$/.test(text) ? formatNumber(text, 4) : text;
  };
  return differences.map((d) => ({
    section: SECTION_LABELS[d.section] ?? d.section,
    field: d.section === "allocations" ? parcelName(d.field) : d.section === "phases"
      ? PHASE_LABELS[d.field] ?? d.field : fieldLabel(d.field),
    from: d.section === "phases" && d.from !== null && d.from !== undefined ? `${String(d.from)} j` : show(d.field, d.from),
    to: d.section === "phases" && d.to !== null && d.to !== undefined ? `${String(d.to)} j` : show(d.field, d.to),
  }));
}

/** Days of a phase written by the user: whole positive number, or empty (to fill). */
export function durationError(value: string): string | undefined {
  if (!value.trim()) return undefined;
  return /^\d+$/.test(value.trim()) && Number(value) >= 1 ? undefined : "Nombre entier de jours (1 ou plus).";
}
