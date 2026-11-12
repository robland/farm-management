/**
 * Campaigns, plans, versions and crop cycles are synced (read offline, FR-110). Designing,
 * computing and validating a plan is done online (OPEN_QUESTIONS Q7): every write goes
 * through the REST API with the version in `If-Match`, then a sync round refreshes the store.
 */

import { useMemo } from "react";

import type { ApiClient } from "../../api/client";
import { results, useRemote } from "../../api/remote";
import type {
  AIRun, Campaign, CropCycle, Paginated, Parcel, PlanVersion, ProductionPlan, Task, Variety,
} from "../../api/types";
import { useLocalEntities } from "../../sync/SyncContext";

export { errorText, results, useRemote } from "../../api/remote";

const withId = <T,>(rows: (T & { _id: string })[]): (T & { id: string })[] => rows.map((r) => ({ ...r, id: r._id }));

export interface Planning {
  campaigns: Campaign[];
  plans: ProductionPlan[];
  versions: PlanVersion[];
  cycles: CropCycle[];
  parcels: Parcel[];
  tasks: (Task & { plan?: string | null })[];
  loading: boolean;
}

export function usePlanning(): Planning {
  const campaigns = useLocalEntities<Campaign>("production_plans.campaign");
  const plans = useLocalEntities<ProductionPlan>("production_plans.plan");
  const versions = useLocalEntities<PlanVersion>("production_plans.plan_version");
  const cycles = useLocalEntities<CropCycle>("production_plans.crop_cycle");
  const parcels = useLocalEntities<Parcel>("fields.parcel");
  const tasks = useLocalEntities<Task & { plan?: string | null }>("tasks.task");
  return useMemo(() => ({
    campaigns: withId(campaigns.rows).sort((a, b) => b.start_date.localeCompare(a.start_date)),
    plans: withId(plans.rows).sort((a, b) => a.name.localeCompare(b.name)),
    versions: withId(versions.rows),
    cycles: withId(cycles.rows),
    parcels: withId(parcels.rows),
    tasks: withId(tasks.rows),
    loading: campaigns.loading || plans.loading,
  }), [campaigns, plans, versions, cycles, parcels, tasks]);
}

export function useVarieties(api: ApiClient, organizationId: string): Variety[] {
  const remote = useRemote<Paginated<Variety>>(api, `/organizations/${organizationId}/varieties/?page_size=200`,
                                               `fms.varieties.${organizationId}`);
  return results(remote.data);
}

/** AI runs of the farm: their suggestions are the ones to decide (no list per version in the API). */
export function useAIRuns(api: ApiClient, farmId: string, enabled: boolean) {
  return useRemote<Paginated<AIRun>>(api, enabled ? `/farms/${farmId}/ai/plan-drafts/?page_size=200` : null,
                                     `fms.ai-runs.${farmId}`);
}

/** Draft of a plan if any, else its current (validated) version, else its newest one. */
export function shownVersion(plan: ProductionPlan, versions: PlanVersion[]): PlanVersion | undefined {
  const own = versions.filter((v) => v.plan === plan.id).sort((a, b) => b.number - a.number);
  return own.find((v) => v.status === "draft") ?? own.find((v) => v.id === plan.current_version) ?? own[0];
}

/** Versioned write on a plan version; returns the fresh version from the server. */
export function versionWrite(api: ApiClient, farmId: string, version: PlanVersion, method: "PATCH" | "PUT" | "POST",
                             action: string, body: unknown): Promise<PlanVersion> {
  const path = `/farms/${farmId}/plan-versions/${version.id}/${action ? `${action}/` : ""}`;
  return api.request<PlanVersion>(method, path, body, { headers: { "If-Match": String(version.version) } });
}
