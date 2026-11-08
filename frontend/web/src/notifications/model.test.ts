import { describe, expect, it } from "vitest";

import {
  addNotification,
  type AppNotification,
  filterNotifications,
  markAllRead,
  markRead,
  MAX_NOTIFICATIONS,
  parseStored,
  unreadCount,
} from "./model";

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
    expect(parseStored(null)).toEqual([]);
    expect(parseStored("not json")).toEqual([]);
    expect(parseStored(JSON.stringify({ a: 1 }))).toEqual([]);
    const ok = { id: "x", type: "info", text: "t", createdAt: now.toISOString(), read: false, farmId: null };
    expect(parseStored(JSON.stringify([ok, { id: 3 }, { ...ok, id: "y", type: "evil" }]))).toEqual([ok]);
  });
});
