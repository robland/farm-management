import { describe, expect, it } from "vitest";

import {
  addNotification,
  type AppNotification,
  filterNotifications,
  localSyncErrorNotification,
  markAllRead,
  markRead,
  MAX_NOTIFICATIONS,
  parseStoredNotifications,
  type QueuedOperationLike,
  sanitizeNotifications,
  syncNotifications,
  unreadCount,
} from "./index";

const now = new Date("2026-11-08T10:00:00Z");
let seq = 0;
const makeId = () => `gen-${++seq}`;

describe("notifications model", () => {
  it("adds newest first and keeps an event notified twice only once", () => {
    let list: AppNotification[] = [];
    list = addNotification(list, { id: "op:1:failed", type: "sync", text: "A", farmId: "f" }, now, makeId);
    list = addNotification(list, { type: "success", text: "B", farmId: "f" }, now, makeId);
    list = addNotification(list, { id: "op:1:failed", type: "sync", text: "A again", farmId: "f" }, now, makeId);
    expect(list.map((n) => n.text)).toEqual(["B", "A"]);
    expect(unreadCount(list)).toBe(2);
  });

  it("caps the history", () => {
    let list: AppNotification[] = [];
    for (let i = 0; i < MAX_NOTIFICATIONS + 5; i++) {
      list = addNotification(list, { type: "info", text: `n${i}`, farmId: null }, now, makeId);
    }
    expect(list).toHaveLength(MAX_NOTIFICATIONS);
    expect(list[0]?.text).toBe(`n${MAX_NOTIFICATIONS + 4}`);
  });

  it("marks as read and filters by type", () => {
    let list: AppNotification[] = [];
    list = addNotification(list, { id: "a", type: "sync", text: "A", farmId: null }, now, makeId);
    list = addNotification(list, { id: "b", type: "issue", text: "B", farmId: null }, now, makeId);
    list = markRead(list, "a");
    expect(unreadCount(list)).toBe(1);
    expect(filterNotifications(list, "issue").map((n) => n.id)).toEqual(["b"]);
    expect(filterNotifications(list, "all")).toHaveLength(2);
    expect(unreadCount(markAllRead(list))).toBe(0);
    // Nothing to change: same array, no re-render.
    const read = markAllRead(list);
    expect(markAllRead(read)).toBe(read);
  });

  it("ignores malformed stored data", () => {
    expect(parseStoredNotifications(null)).toEqual([]);
    expect(parseStoredNotifications("not json")).toEqual([]);
    expect(parseStoredNotifications(JSON.stringify({ a: 1 }))).toEqual([]);
    const ok = { id: "x", type: "info", text: "t", createdAt: now.toISOString(), read: false, farmId: null };
    expect(parseStoredNotifications(JSON.stringify([ok, { id: 3 }, { ...ok, id: "y", type: "evil" }])))
      .toEqual([ok]);
    expect(sanitizeNotifications([null, ok])).toEqual([ok]);
  });
});

const op = (patch: Partial<QueuedOperationLike>): QueuedOperationLike => ({
  opId: "op-1", opType: "create", entityType: "fields.parcel", payload: {}, status: "pending", attempts: 1,
  ...patch,
});

describe("syncNotifications", () => {
  it("reports sent entries, refusals, conflicts and new tasks", () => {
    const list = syncNotifications({
      farmId: "f",
      report: { applied: 3 },
      operations: [
        op({ opId: "a", status: "failed",
             lastError: { code: "validation_error", message: "Données invalides.", fieldErrors: { code: ["Déjà utilisé."] } } }),
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
    const first = syncNotifications({ farmId: "f", report: { applied: 0 }, operations: [failed], newTaskCount: 0 });
    const again = syncNotifications({ farmId: "f", report: { applied: 0 }, operations: [failed], newTaskCount: 0 });
    expect(first[0]?.id).toBe(again[0]?.id);
    const retried = syncNotifications({ farmId: "f", report: { applied: 0 },
                                        operations: [{ ...failed, attempts: 3 }], newTaskCount: 0 });
    expect(retried[0]?.id).not.toBe(first[0]?.id);
  });

  it("says nothing when nothing happened", () => {
    expect(syncNotifications({ farmId: "f", report: { applied: 0 }, operations: [op({})], newTaskCount: 0 }))
      .toEqual([]);
  });

  it("describes a local failure of the sync loop, with a stable id", () => {
    const n = localSyncErrorNotification("f", new Error("disk full"));
    expect(n).toMatchObject({ id: "local-error:disk full", type: "sync", action: { tab: "sync" } });
    expect(n.text).toBe("La synchronisation a échoué sur cet appareil (disk full). Nouvel essai automatique.");
  });
});
