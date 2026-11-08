/**
 * SqliteStore tests on Node's built-in SQLite (same SQL engine as the device),
 * through an adapter mimicking expo-sqlite's async API.
 */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

import { NetworkError, type PushOperation, SyncEngine, type Transport } from "@fms/sync-core";
import { describe, expect, it } from "vitest";

import { migrate, SCHEMA_VERSION, type SqlDatabase, SqliteStore } from "./sqliteStore";

type Param = string | number | null;

function nodeDatabase(path = ":memory:"): SqlDatabase & { close(): void } {
  const db = new DatabaseSync(path);
  return {
    async execAsync(source) { db.exec(source); },
    async runAsync(source, params: Param[]) { return db.prepare(source).run(...params); },
    async getAllAsync<T>(source: string, params: Param[]) {
      return db.prepare(source).all(...params) as T[];
    },
    async getFirstAsync<T>(source: string, params: Param[]) {
      return (db.prepare(source).get(...params) as T | undefined) ?? null;
    },
    async withTransactionAsync(task) {
      db.exec("BEGIN");
      try {
        await task();
        db.exec("COMMIT");
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
    },
    close() { db.close(); },
  };
}

class Server implements Transport {
  online = false;
  received: PushOperation[] = [];
  async push(_d: string, ops: PushOperation[]) {
    if (!this.online) throw new NetworkError("offline");
    this.received.push(...ops);
    return ops.map((op) => ({ op_id: op.op_id, status: "applied" as const, entity_version: 1 }));
  }
  async pull(_f: string, cursor: number) {
    if (!this.online) throw new NetworkError("offline");
    const changes = this.received.slice(cursor).map((op, i) => ({
      seq: cursor + i + 1, entity_type: op.entity_type, entity_id: op.entity_id,
      operation: "upsert" as const, version: 1, data: op.payload }));
    return { changes, next_cursor: cursor + changes.length, has_more: false, purge: [],
             server_seq: this.received.length };
  }
}

describe("SqliteStore", () => {
  it("migrates the local schema idempotently", async () => {
    const db = nodeDatabase();
    await migrate(db);
    await migrate(db);
    const row = await db.getFirstAsync<{ user_version: number }>("PRAGMA user_version", []);
    expect(row?.user_version).toBe(SCHEMA_VERSION);
  });

  it("keeps the outbox across an app restart and syncs once online", async () => {
    const file = join(mkdtempSync(join(tmpdir(), "fms-")), "fms.db");
    const server = new Server();
    const first = nodeDatabase(file);
    await migrate(first);
    const engine = new SyncEngine(new SqliteStore(first), server, { deviceId: "d", authorId: "u" });
    await engine.enqueue({ farmId: "f", opType: "create", entityType: "harvest.harvest_record",
                           entityId: "h1", payload: { quantity: "120", unit: "kg" } });
    expect((await engine.sync("f")).offline).toBe(true);
    first.close(); // the app is killed

    const second = nodeDatabase(file);
    await migrate(second);
    const store = new SqliteStore(second);
    const restarted = new SyncEngine(store, server, { deviceId: "d", authorId: "u",
                                                     now: () => Date.now() + 60_000 });
    expect((await restarted.stats("f")).pending).toBe(1);
    server.online = true;
    expect((await restarted.sync("f")).applied).toBe(1);
    expect(server.received).toHaveLength(1);
    expect(await store.listOperations("f")).toEqual([]);
    expect((await store.getEntity("harvest.harvest_record", "h1"))?.data.quantity).toBe("120");
    second.close();
  });

  it("supports nested transactions and rolls back on failure", async () => {
    const db = nodeDatabase();
    await migrate(db);
    const store = new SqliteStore(db);
    await expect(store.transaction(async () => {
      await store.setCursor("f", 7);
      await store.transaction(async () => store.setCursor("f", 8));
      throw new Error("boom");
    })).rejects.toThrow("boom");
    expect(await store.getCursor("f")).toBe(0);
  });

  it("counts unsent operations of every farm (logout warning)", async () => {
    const db = nodeDatabase();
    await migrate(db);
    const store = new SqliteStore(db);
    const engine = new SyncEngine(store, new Server(), { deviceId: "d", authorId: "u" });
    expect(await store.countUnsent()).toBe(0);
    await engine.enqueue({ farmId: "f1", opType: "create", entityType: "agronomy.observation",
                           entityId: "o1", payload: { kind: "pest" } });
    await engine.enqueue({ farmId: "f2", opType: "create", entityType: "finance.transaction",
                           entityId: "t1", payload: { amount: "5000" } });
    expect(await store.countUnsent()).toBe(2);
  });

  it("upserts, purges and isolates farms", async () => {
    const db = nodeDatabase();
    await migrate(db);
    const store = new SqliteStore(db);
    const record = { entityType: "tasks.task", entityId: "t", farmId: "f1", version: 1,
                     data: { title: "A" } };
    await store.putEntities([record]);
    await store.putEntities([{ ...record, version: 2, data: { title: "B" } }]);
    expect((await store.getEntity("tasks.task", "t"))?.data.title).toBe("B");
    expect(await store.listEntities("f2", "tasks.task")).toEqual([]);
    await store.purgeEntityTypes("f1", ["tasks.task"]);
    expect(await store.listEntities("f1", "tasks.task")).toEqual([]);
  });
});
