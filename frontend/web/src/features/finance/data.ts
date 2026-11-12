/**
 * Data access of the Finances tab. Accounts and transactions come from the local store
 * (synced, usable offline). Reports, validation and account management need the server
 * (api/remote.ts: last answer cached and dated).
 */

import type { ApiClient } from "../../api/client";
import { results, useRemote } from "../../api/remote";
import type { Campaign, FinanceCategory, Paginated } from "../../api/types";
import { useLocalEntities } from "../../sync/SyncContext";

export { errorText, type Remote, results, useRemote } from "../../api/remote";

/** All finance categories of the organization (expense, income, investment). */
export function useCategories(api: ApiClient, organizationId: string): FinanceCategory[] {
  const remote = useRemote<Paginated<FinanceCategory>>(
    api, `/organizations/${organizationId}/finance-categories/?page_size=200`, `fms.categories.${organizationId}`);
  return results(remote.data).filter((c) => c.is_active !== false);
}

/** Campaigns are synced with plans.view: read locally, offline included. */
export function useCampaigns(): Campaign[] {
  return useLocalEntities<Campaign>("production_plans.campaign").rows.map((c) => ({ ...c, id: c._id }))
    .sort((a, b) => b.start_date.localeCompare(a.start_date));
}

/** One online action on a transaction. Versioned actions send `If-Match` (409 when stale). */
export function transactionAction(api: ApiClient, farmId: string, id: string, action: string,
                                  body: object | undefined, version?: number): Promise<unknown> {
  return api.request("POST", `/farms/${farmId}/transactions/${id}/${action}/`, body ?? {},
                     version ? { headers: { "If-Match": String(version) } } : {});
}
