/**
 * Sync engine tests (OFFLINE_SYNC.md §10): connection loss, return, duplicates,
 * replay, concurrent changes, partial failure, crash recovery.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { SyncEngine, backoffMs } from "./engine";
import { MemoryStore } from "./memoryStore";
import {
  AuthError,
  CursorExpiredError,
  NetworkError,
  type PullResponse,
  type PushOperation,
  type PushResult,
  type Transport,
} from "./types";

const FARM = "farm-1";

/** A fake server keeping per-entity versions and an idempotent receipt per op_id. */
class FakeServer implements Transport {
  online = true;
  authValid = true;
  receipts = new Map<string, PushResult>();
  entities = new Map<string, { type: string; version: number; data: Record<string, unknown> }>();
  log: { seq: number; id: string; deleted: boolean }[] = [];
  pushes: PushOperation[][] = [];
  reject = new Map<string, PushResult["error"]>();
  conflictOn = new Set<string>();
  dropResponse = false;
  cursorExpired = false;

  private change(id: string, deleted = false): void {
    this.log.push({ seq: this.log.length + 1, id, deleted });
  }

  async push(_device: string, operations: PushOperation[]): Promise<PushResult[]> {
    if (!this.online) throw new NetworkError("offline");
    if (!this.authValid) throw new AuthError("expired");
    this.pushes.push(operations);
    const results = operations.map((op) => {
      const known = this.receipts.get(op.op_id);
      if (known) return known;
      const rejection = this.reject.get(op.entity_id);
      if (rejection) return { op_id: op.op_id, status: "rejected", error: rejection } as PushResult;
      if (this.conflictOn.has(op.entity_id)) {
        const result: PushResult = { op_id: op.op_id, status: "conflict", conflict_id: "c-1" };
        this.receipts.set(op.op_id, result);
        return result;
      }
      const current = this.entities.get(op.entity_id);
      let version = 1;
      if (op.op_type === "create") {
        this.entities.set(op.entity_id, { type: op.entity_type, version: 1, data: op.payload });
      } else if (current) {
        version = current.version + 1;
        this.entities.set(op.entity_id, {
          ...current,
          version,
          data: { ...current.data, ...op.payload },
        });
      }
      this.change(op.entity_id, op.op_type === "delete");
      const result: PushResult = { op_id: op.op_id, status: "applied", entity_version: version };
      this.receipts.set(op.op_id, result);
      return result;
    });
    if (this.dropResponse) {
      this.dropResponse = false;
      throw new NetworkError("response lost after server applied the batch");
    }
    return results;
  }

  async pull(_farm: string, cursor: number, limit: number): Promise<PullResponse> {
    if (!this.online) throw new NetworkError("offline");
    if (this.cursorExpired && cursor > 0) {
      this.cursorExpired = false;
      throw new CursorExpiredError("410");
    }
    const page = this.log.filter((entry) => entry.seq > cursor).slice(0, limit);
    const changes = page.map((entry) => {
      const entity = this.entities.get(entry.id);
      return entry.deleted || !entity
        ? { seq: entry.seq, entity_type: "fields.parcel", entity_id: entry.id,
            operation: "delete" as const, version: 0 }
        : { seq: entry.seq, entity_type: entity.type, entity_id: entry.id,
            operation: "upsert" as const, version: entity.version, data: entity.data };
    });
    const last = page.at(-1);
    return {
      changes,
      next_cursor: last ? last.seq : cursor,
      has_more: this.log.some((entry) => entry.seq > (last?.seq ?? cursor)),
      purge: [],
      server_seq: this.log.length,
    };
  }
}

let store: MemoryStore;
let server: FakeServer;
let clock: number;
let engine: SyncEngine;
let counter: number;

beforeEach(() => {
  store = new MemoryStore();
  server = new FakeServer();
  clock = 1_000_000;
  counter = 0;
  engine = new SyncEngine(store, server, {
    deviceId: "device-1",
    authorId: "user-1",
    now: () => clock,
    newId: () => `op-${++counter}`,
    pullLimit: 2,
  });
});

const createParcel = (id: string, name = "P") =>
  engine.enqueue({ farmId: FARM, opType: "create", entityType: "fields.parcel", entityId: id,
                   payload: { name, code: id, area_m2: "100" } });

describe("offline queue", () => {
  it("keeps operations while offline and sends them when the connection returns", async () => {
    server.online = false;
    await createParcel("p1");
    const offline = await engine.sync(FARM);
    expect(offline.offline).toBe(true);
    expect((await engine.stats(FARM)).pending).toBe(1);
    expect(store.operations.get("op-1")?.attempts).toBe(1);

    server.online = true;
    clock += backoffMs(1); // the retry delay elapsed
    const online = await engine.sync(FARM);
    expect(online.applied).toBe(1);
    // Confirmed AND pulled back: the operation can be dropped, the entity is server state.
    expect(store.operations.size).toBe(0);
    expect((await store.getEntity("fields.parcel", "p1"))?.version).toBe(1);
  });

  it("respects the exponential backoff", async () => {
    server.online = false;
    await createParcel("p1");
    await engine.sync(FARM);
    server.online = true;
    await engine.sync(FARM); // too early: not resent
    expect(server.pushes).toHaveLength(0);
    clock += backoffMs(1);
    await engine.sync(FARM);
    expect(server.pushes).toHaveLength(1);
  });

  it("recovers from a crash during push without duplicating", async () => {
    await createParcel("p1");
    // Simulate a crash: the op was marked syncing, the server applied it, the app died.
    await store.updateOperation("op-1", { status: "syncing" });
    await server.push("device-1", [
      { op_id: "op-1", farm_id: FARM, op_type: "create", entity_type: "fields.parcel",
        entity_id: "p1", payload: { name: "P" }, base_version: null, base_values: {},
        created_at: "", author_id: "user-1", depends_on: [] },
    ]);
    const report = await engine.sync(FARM);
    expect(report.applied).toBe(1);
    expect(server.entities.size).toBe(1); // replay answered from the receipt
    expect(store.operations.size).toBe(0);
  });

  it("replays safely when the response is lost after the server applied the batch", async () => {
    await createParcel("p1");
    server.dropResponse = true;
    expect((await engine.sync(FARM)).offline).toBe(true);
    expect(store.operations.get("op-1")?.status).toBe("pending");
    clock += backoffMs(1);
    await engine.sync(FARM);
    expect(server.pushes).toHaveLength(2);
    expect([...server.entities.keys()]).toEqual(["p1"]); // applied once
    expect(store.operations.size).toBe(0);
  });

  it("handles a partial batch failure", async () => {
    await createParcel("ok1");
    await createParcel("bad");
    await createParcel("ok2");
    server.reject.set("bad", { code: "validation_error", message: "Code déjà utilisé",
                               retryable: false });
    const report = await engine.sync(FARM);
    expect(report).toMatchObject({ applied: 2, failed: 1 });
    const failed = store.operations.get("op-2");
    expect(failed?.status).toBe("failed");
    expect(failed?.lastError?.code).toBe("validation_error");
    // The user fixes the data and retries: same op id, the server has no receipt for it.
    server.reject.delete("bad");
    await engine.retry("op-2", FARM, { payload: { name: "P", code: "bad-2" } });
    expect((await engine.sync(FARM)).applied).toBe(1);
    expect(store.operations.size).toBe(0);
  });

  it("retries retryable rejections later instead of failing", async () => {
    await createParcel("p1");
    server.reject.set("p1", { code: "integrity_error", message: "", retryable: true });
    await engine.sync(FARM);
    expect(store.operations.get("op-1")?.status).toBe("pending");
  });

  it("marks conflicts and never applies them locally as synced", async () => {
    await createParcel("p1");
    await engine.sync(FARM);
    server.conflictOn.add("p1");
    await engine.enqueue({ farmId: FARM, opType: "update", entityType: "fields.parcel",
                           entityId: "p1", payload: { name: "Mine" }, baseVersion: 1,
                           baseValues: { name: "P" } });
    const report = await engine.sync(FARM);
    expect(report.conflicts).toBe(1);
    const conflict = [...store.operations.values()][0];
    expect(conflict?.status).toBe("conflict");
    expect(conflict?.conflictId).toBe("c-1");
    // The local view still shows the user's pending value, flagged as in conflict.
    const [row] = await engine.view(FARM, "fields.parcel");
    expect(row?.data.name).toBe("Mine");
    expect(row?.local).toBe("conflict");
    const abandoned = await engine.abandon(conflict!.opId, FARM);
    expect(abandoned.payload).toEqual({ name: "Mine" });
  });

  it("asks for login on auth errors and keeps the queue", async () => {
    await createParcel("p1");
    server.authValid = false;
    const report = await engine.sync(FARM);
    expect(report.authRequired).toBe(true);
    expect(store.operations.get("op-1")?.status).toBe("pending");
  });
});

describe("compaction", () => {
  it("merges successive updates and keeps the oldest base values", async () => {
    const first = await engine.enqueue({ farmId: FARM, opType: "update",
      entityType: "fields.parcel", entityId: "p1", payload: { name: "A" }, baseVersion: 3,
      baseValues: { name: "Origin" } });
    const second = await engine.enqueue({ farmId: FARM, opType: "update",
      entityType: "fields.parcel", entityId: "p1", payload: { name: "B", notes: "n" },
      baseVersion: 3, baseValues: { name: "A", notes: "" } });
    expect(second).toBe(first);
    const op = store.operations.get(first);
    expect(op?.payload).toEqual({ name: "B", notes: "n" });
    expect(op?.baseValues).toEqual({ name: "Origin", notes: "" });
  });

  it("folds updates into a pending creation", async () => {
    await createParcel("p1", "Draft");
    await engine.enqueue({ farmId: FARM, opType: "update", entityType: "fields.parcel",
                           entityId: "p1", payload: { name: "Final" } });
    expect(store.operations.size).toBe(1);
    expect(store.operations.get("op-1")?.payload.name).toBe("Final");
  });

  it("never merges financial operations", async () => {
    for (const amount of ["1000", "1000"]) {
      await engine.enqueue({ farmId: FARM, opType: "update", entityType: "finance.transaction",
                             entityId: "t1", payload: { amount } });
    }
    expect(store.operations.size).toBe(2);
  });
});

describe("pull", () => {
  it("paginates, applies deletions and is resumable", async () => {
    for (const id of ["a", "b", "c"]) await createParcel(id);
    await engine.sync(FARM);
    expect((await store.listEntities(FARM, "fields.parcel")).map((e) => e.entityId).sort())
      .toEqual(["a", "b", "c"]);
    expect(await store.getCursor(FARM)).toBe(3);
    server.entities.delete("b");
    server.log.push({ seq: 4, id: "b", deleted: true });
    await engine.sync(FARM);
    expect(await store.getEntity("fields.parcel", "b")).toBeUndefined();
  });

  it("reloads everything on an expired cursor without touching the outbox", async () => {
    await createParcel("a");
    await engine.sync(FARM);
    server.online = false;
    await createParcel("pending-local");
    server.online = true;
    server.cursorExpired = true;
    server.log.push({ seq: server.log.length + 1, id: "a", deleted: false });
    await engine.pull(FARM, { pushed: 0, applied: 0, conflicts: 0, failed: 0, pulled: 0,
                              offline: false, authRequired: false });
    expect(store.operations.get("op-2")?.status).toBe("pending");
    expect(await store.getEntity("fields.parcel", "a")).toBeDefined();
  });

  it("rolls back a page when applying it fails", async () => {
    await createParcel("a");
    await engine.push(FARM, { pushed: 0, applied: 0, conflicts: 0, failed: 0, pulled: 0,
                              offline: false, authRequired: false });
    const original = store.putEntities.bind(store);
    store.putEntities = async () => { throw new Error("disk full"); };
    await expect(engine.pull(FARM, { pushed: 0, applied: 0, conflicts: 0, failed: 0,
                                     pulled: 0, offline: false, authRequired: false }))
      .rejects.toThrow("disk full");
    expect(await store.getCursor(FARM)).toBe(0); // the page will be replayed
    store.putEntities = original;
  });
});

describe("local view", () => {
  it("overlays pending creations, updates and deletions on server state", async () => {
    await createParcel("p1", "Server");
    await engine.sync(FARM);
    server.online = false;
    await engine.enqueue({ farmId: FARM, opType: "update", entityType: "fields.parcel",
                           entityId: "p1", payload: { name: "Local" }, baseVersion: 1 });
    await createParcel("p2", "New");
    const rows = await engine.view(FARM, "fields.parcel");
    const byId = Object.fromEntries(rows.map((row) => [row.entityId, row]));
    expect(byId.p1?.data.name).toBe("Local");
    expect(byId.p1?.local).toBe("pending");
    expect(byId.p2?.local).toBe("pending");
    await engine.enqueue({ farmId: FARM, opType: "delete", entityType: "fields.parcel",
                           entityId: "p1", baseVersion: 1 });
    const after = await engine.view(FARM, "fields.parcel");
    expect(after.find((row) => row.entityId === "p1")?.deleted).toBe(true);
  });
});
