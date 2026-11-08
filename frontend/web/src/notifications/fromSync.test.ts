import type { LocalOperation, SyncReport } from "@fms/sync-core";
import { describe, expect, it } from "vitest";

import { syncNotifications } from "./fromSync";

const report = (patch: Partial<SyncReport> = {}): SyncReport => ({
  pushed: 0, applied: 0, conflicts: 0, failed: 0, pulled: 0, offline: false, authRequired: false, ...patch,
});

const op = (patch: Partial<LocalOperation>): LocalOperation => ({
  opId: "op-1", opType: "create", entityType: "fields.parcel", entityId: "p1", farmId: "f", payload: {},
  baseVersion: null, baseValues: {}, authorId: "u", deviceId: "d", createdAt: "2026-11-08T10:00:00Z",
  version: 1, status: "pending", attempts: 1, ...patch,
});

describe("syncNotifications", () => {
  it("reports sent entries, refusals, conflicts and new tasks", () => {
    const list = syncNotifications({
      farmId: "f",
      report: report({ applied: 3 }),
      operations: [
        op({ opId: "a", status: "failed", lastError: { code: "validation_error", message: "Données invalides.",
                                                         retryable: false, fieldErrors: { code: ["Déjà utilisé."] } } }),
        op({ opId: "b", status: "conflict", entityType: "tasks.task", opType: "update" }),
        op({ opId: "c", status: "pending" }),
      ],
      newTaskCount: 2,
    });
    expect(list.map((n) => [n.type, n.text])).toEqual([
      ["success", "3 saisies envoyées au serveur."],
      ["sync", "Nouvelle parcelle refusée par le serveur. Données invalides. code : Déjà utilisé."],
      ["issue", "Modification : tâche : conflit avec une modification faite ailleurs, à vérifier."],
      ["info", "2 nouvelles tâches planifiées."],
    ]);
    expect(list[1]).toMatchObject({ id: "op:a:failed:1", action: { tab: "sync" } });
  });

  it("uses one stable id per refusal so a repeated sync does not notify twice", () => {
    const failed = op({ status: "failed", attempts: 2 });
    const first = syncNotifications({ farmId: "f", report: report(), operations: [failed], newTaskCount: 0 });
    const again = syncNotifications({ farmId: "f", report: report(), operations: [failed], newTaskCount: 0 });
    expect(first[0]?.id).toBe(again[0]?.id);
    const retried = syncNotifications({ farmId: "f", report: report(), operations: [{ ...failed, attempts: 3 }],
                                        newTaskCount: 0 });
    expect(retried[0]?.id).not.toBe(first[0]?.id);
  });

  it("says nothing when nothing happened", () => {
    expect(syncNotifications({ farmId: "f", report: report({ offline: true }), operations: [op({})],
                               newTaskCount: 0 })).toEqual([]);
  });
});
