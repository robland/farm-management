/** Task list organisation for field screens (FR-062: "late" is derived, never stored). */

import type { LocalState } from "./labels";

export interface TaskLike {
  id: string;
  status: string;
  planned_start_date: string;
  planned_end_date: string;
}

const OPEN = new Set(["todo", "in_progress"]);

export function isLate(task: TaskLike, today: string): boolean {
  return OPEN.has(task.status) && task.planned_end_date < today;
}

export interface TaskGroups<T> {
  late: T[];
  today: T[];
  upcoming: T[];
  /** Done or awaiting a supervisor check. */
  finished: T[];
}

/** Late / due today / upcoming / finished. Cancelled tasks are not shown. */
export function groupTasks<T extends TaskLike>(tasks: T[], today: string): TaskGroups<T> {
  const groups: TaskGroups<T> = { late: [], today: [], upcoming: [], finished: [] };
  const sorted = [...tasks].sort((a, b) =>
    a.planned_start_date.localeCompare(b.planned_start_date)
    || a.planned_end_date.localeCompare(b.planned_end_date));
  for (const task of sorted) {
    if (task.status === "cancelled") continue;
    if (!OPEN.has(task.status)) groups.finished.push(task);
    else if (task.planned_end_date < today) groups.late.push(task);
    else if (task.planned_start_date <= today) groups.today.push(task);
    else groups.upcoming.push(task);
  }
  return groups;
}

/**
 * Tasks with a field report still in the local queue. The task itself only becomes
 * "done" after the server applied the report, so without this a second tap on
 * "Terminer" would send a second report (the server keeps both).
 */
export function pendingReports(
  reports: { task?: unknown; _local: LocalState | null }[],
): Map<string, LocalState> {
  const result = new Map<string, LocalState>();
  for (const report of reports) {
    if (report._local && report._local !== "synced" && typeof report.task === "string") {
      result.set(report.task, report._local);
    }
  }
  return result;
}
