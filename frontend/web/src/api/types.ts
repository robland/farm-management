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
  currency: string;
  is_active: boolean;
}

export interface Transaction {
  id: string;
  kind: string;
  status: string;
  business_date: string;
  amount: string;
  currency: string;
  description: string;
}

export interface FinanceCategory {
  id: string;
  kind: "expense" | "income";
  name: string;
}

export interface Paginated<T> {
  count: number;
  results: T[];
}
