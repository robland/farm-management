/** Notifications derived from a synchronization round (pure, unit tested). */

import { describeError, describeOperation } from "@fms/shared";
import type { LocalOperation, SyncReport } from "@fms/sync-core";

import type { NotificationInput } from "./model";

const plural = (n: number, one: string, many: string) => (n > 1 ? many : one);

export function syncNotifications(input: {
  farmId: string;
  report: SyncReport;
  operations: LocalOperation[];
  newTaskCount: number;
}): NotificationInput[] {
  const { farmId, report } = input;
  const out: NotificationInput[] = [];
  if (report.applied > 0) {
    out.push({ type: "success", farmId,
               text: `${report.applied} ${plural(report.applied, "saisie envoyée", "saisies envoyées")} au serveur.` });
  }
  for (const op of input.operations) {
    if (op.status !== "failed" && op.status !== "conflict") continue;
    const reason = describeError(op.lastError);
    // One notification per refusal: a retried operation that fails again is notified again.
    const id = `op:${op.opId}:${op.status}:${op.attempts}`;
    out.push(op.status === "failed"
      ? { id, type: "sync", farmId, text: `${describeOperation(op)} refusée par le serveur.${reason ? ` ${reason}` : ""}`,
          action: { label: "Ouvrir la synchronisation", tab: "sync" } }
      : { id, type: "issue", farmId,
          text: `${describeOperation(op)} : conflit avec une modification faite ailleurs, à vérifier.${
            reason ? ` ${reason}` : ""}`,
          action: { label: "Ouvrir la synchronisation", tab: "sync" } });
  }
  if (input.newTaskCount > 0) {
    out.push({ type: "info", farmId, action: { label: "Voir les tâches", tab: "tasks" },
               text: `${input.newTaskCount} ${plural(input.newTaskCount, "nouvelle tâche planifiée",
                 "nouvelles tâches planifiées")}.` });
  }
  return out;
}
