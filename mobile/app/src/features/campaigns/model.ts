/** Synced planning data as read on the phone (scenario S11, read-only). */

import { todayIso } from "@fms/shared";

export interface Campaign { id: string; name: string; start_date: string; end_date: string; status: string }
export interface Plan { id: string; campaign: string; name: string; variety_name: string; status: string;
                        current_version: string | null }
export interface Phase { phase_code: string; sequence: number; duration_days: number | null; start_date: string | null;
                         end_date: string | null }
export interface Version { id: string; plan: string; number: number; status: string; phases: Phase[];
                           allocations: { parcel: string; allocated_area_m2: string }[];
                           calculations: { calc_type: string; scope: string; outputs: Record<string, { value: unknown }> }[];
                           planting_spec: Record<string, unknown> | null; validated_at: string | null }

/** The phase running today, if any. */
export function currentPhase(phases: Phase[], today = todayIso()): Phase | undefined {
  return phases.find((p) => p.start_date && p.end_date && p.start_date <= today && today <= p.end_date);
}
