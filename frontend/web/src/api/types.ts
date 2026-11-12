/** Subset of the API contract used by the web client (OpenAPI: /api/v1/schema/). */

export interface MeFarm {
  id: string;
  name: string;
  organization_id: string;
  role: string | null;
  is_org_admin: boolean;
  permissions: string[];
}

export interface Me {
  user: { id: string; full_name: string; email: string | null; phone: string | null };
  organizations: { id: string; name: string; is_org_admin: boolean }[];
  farms: MeFarm[];
}

export interface Parcel {
  id: string;
  name: string;
  code: string;
  area_m2: string;
  soil_type?: string;
  soil_ph?: string | null;
  water_availability?: string;
  status?: string;
  version?: number;
}

export interface Task {
  id: string;
  title: string;
  task_type: string;
  status: "todo" | "in_progress" | "done" | "cancelled" | "to_verify";
  planned_start_date: string;
  planned_end_date: string;
  is_late?: boolean;
  parcel: string | null;
}

export interface TreasuryAccount {
  id: string;
  name: string;
  kind: string;
  role?: "main" | "member" | "operating";
  holder?: string | null;
  currency: string;
  institution?: string;
  account_ref?: string;
  is_active: boolean;
  version?: number;
}

export interface Transaction {
  id: string;
  kind: string;
  status: string;
  business_date: string;
  amount: string;
  currency: string;
  description: string;
  category?: string | null;
  counterparty?: string | null;
  campaign?: string | null;
  loan?: string | null;
  reverses?: string | null;
  corrects?: string | null;
  possible_duplicate?: boolean;
  created_offline?: boolean;
  validated_by?: string | null;
  validated_at?: string | null;
  rejected_reason?: string;
  revision?: number;
  entries?: { account: string; amount: string }[];
  created_by?: string | null;
  created_at?: string;
  version?: number;
}

export interface FinanceCategory {
  id: string;
  kind: "expense" | "income" | "investment";
  name: string;
  is_capex?: boolean;
  is_active?: boolean;
}

/** Report endpoints send amounts as JSON numbers for now (OPEN_QUESTIONS Q37). */
type Amount = string | number;

export interface AccountBalance {
  account: string;
  name: string;
  role: string;
  holder: string | null;
  currency: string;
  balance: Amount;
  pending: Amount;
  provisional_balance: Amount;
  is_active: boolean;
}

export interface MemberStatement {
  account: string;
  name: string;
  holder: string;
  holder_name: string;
  currency: string;
  contributed: Amount;
  pending_contributions: Amount;
  transferred_to_treasury: Amount;
  balance: Amount;
}

export interface LoanPosition {
  loan: string;
  lender: string;
  currency: string;
  started_on: string;
  principal: Amount;
  disbursed: Amount;
  pending_disbursement: Amount;
  repaid: Amount;
  pending_repayment: Amount;
  outstanding: Amount;
}

export interface Campaign {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: "planned" | "active" | "closed";
  notes?: string;
  version?: number;
}

export interface ProductionPlan {
  id: string;
  campaign: string;
  variety: string;
  variety_name: string;
  name: string;
  status: string;
  current_version: string | null;
  version: number;
  updated_at?: string;
}

export interface PlanAllocation {
  parcel: string;
  allocated_area_m2: string;
  non_plantable_area_m2: string;
  plot_length_m: string | null;
  plot_width_m: string | null;
  notes: string;
}

export interface PlanPhase {
  phase_code: string;
  sequence: number;
  duration_days: number | null;
  start_date: string | null;
  end_date: string | null;
}

export interface Provenance {
  field_path: string;
  source_kind: "document" | "calculation" | "ai_suggestion" | "user_input";
  technical_data_item: string | null;
  note: string;
}

export interface CalculationRecord {
  id: string;
  calc_type: string;
  engine_version: string;
  scope: string;
  inputs: Record<string, { value: unknown; unit: string }>;
  outputs: Record<string, { value: unknown; unit: string }>;
  formula: string;
  assumptions: string[];
  warnings: string[];
  details: Record<string, unknown>;
  created_at: string;
}

export interface PlanVersion {
  id: string;
  plan: string;
  number: number;
  status: "draft" | "validated" | "superseded" | "rejected";
  origin: string;
  based_on: string | null;
  technical_data_set: string | null;
  planned_start_date: string | null;
  planned_end_date: string | null;
  target_yield_kg_per_ha: string | null;
  objectives: string;
  constraints_notes: string;
  change_note: string;
  validated_by: string | null;
  validated_at: string | null;
  planting_spec: Record<string, string | number | null> | null;
  allocations: PlanAllocation[];
  phases: PlanPhase[];
  provenances: Provenance[];
  calculations: CalculationRecord[];
  version: number;
  updated_at?: string;
}

export interface CropCycle {
  id: string;
  plan: string;
  plan_version: string;
  parcel: string;
  area_m2: string;
  start_date: string;
  end_date: string;
  status: string;
}

export interface Variety {
  id: string;
  name: string;
  crop_name: string;
}

export interface AISuggestion {
  id: string;
  plan_version: string;
  field_path: string;
  value: unknown;
  rationale: string;
  status: "suggested" | "accepted" | "modified" | "rejected";
}

export interface AIRun {
  id: string;
  status: string;
  plan_version: string | null;
  missing_info: { field: string; question: string }[];
  suggestions: AISuggestion[];
  error_message: string;
  usage: { estimated_cost: string | number | null; cost_currency: string }[];
  created_at: string;
}

export interface ComputeOutcome {
  complete: boolean;
  missing: { scope: string; fields: string[]; reason?: string }[];
  errors: { scope: string; field: string; reason: string }[];
  totals: Record<string, string | number>;
}

export interface Revision {
  revision: number;
  snapshot: Record<string, unknown>;
  changed_by: string;
  changed_at: string;
  reason: string;
}

export interface Paginated<T> {
  count: number;
  results: T[];
}
