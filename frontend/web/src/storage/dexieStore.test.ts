import { NetworkError, type PullResponse, type PushOperation, SyncEngine, type Transport } from "@fms/sync-core";
import { afterEach, describe, expect, it } from "vitest";

import { DexieStore } from "./dexieStore";

class OfflineThenOnline implements Transport {
  online = false;
  received: PushOperation[] = [];

  async push(_device: string, operations: PushOperation[]) {
    if (!this.online) throw new NetworkError("offline");
    this.received.push(...operations);
    return operations.map((op) => ({ op_id: op.op_id, status: "applied" as const, entity_version: 1 }));
  }

  async pull(_farm: string, cursor: number): Promise<PullResponse> {
    if (!this.online) throw new NetworkError("offline");
    const changes = cursor === 0
      ? this.received.map((op, index) => ({
          seq: index + 1, entity_type: op.entity_type, entity_id: op.entity_id,
          operation: "upsert" as const, version: 1, data: { id: op.entity_id, ...op.payload } }))
      : [];
    return { changes, next_cursor: cursor + changes.length, has_more: false, purge: [],
             server_seq: this.received.length };
  }
}

const stores: DexieStore[] = [];
afterEach(async () => {
  for (const store of stores.splice(0)) await store.db.delete();
});

describe("DexieStore", () => {
  it("survives a reload: operations persist in IndexedDB until confirmed", async () => {
    const transport = new OfflineThenOnline();
    const first = new DexieStore("user-reload");
    stores.push(first);
    const engine = new SyncEngine(first, transport, { deviceId: "d", authorId: "u" });
    await engine.enqueue({ farmId: "f", opType: "create", entityType: "finance.transaction",
                           entityId: "t1", payload: { amount: "15000" } });
    expect((await engine.sync("f")).offline).toBe(true);
    first.db.close();

    // A new tab / reload opens the same database: nothing was lost.
    const second = new DexieStore("user-reload");
    stores.push(second);
    const reloaded = new SyncEngine(second, transport, { deviceId: "d", authorId: "u",
                                                        now: () => Date.now() + 60_000 });
    expect((await reloaded.stats("f")).pending).toBe(1);
    transport.online = true;
    const report = await reloaded.sync("f");
    expect(report.applied).toBe(1);
    expect(transport.received).toHaveLength(1);
    expect(await second.listOperations("f")).toEqual([]);
    expect((await second.getEntity("finance.transaction", "t1"))?.data.amount).toBe("15000");
  });

  it("isolates users and farms", async () => {
    const a = new DexieStore("user-a");
    const b = new DexieStore("user-b");
    stores.push(a, b);
    await a.putEntities([{ entityType: "fields.parcel", entityId: "p", farmId: "f1", version: 1,
                           data: {} }]);
    expect(await b.listEntities("f1", "fields.parcel")).toEqual([]);
    expect(await a.listEntities("f2", "fields.parcel")).toEqual([]);
    await a.purgeEntityTypes("f1", ["fields.parcel"]);
    expect(await a.listEntities("f1", "fields.parcel")).toEqual([]);
  });

  it("rolls back a failed transaction", async () => {
    const store = new DexieStore("user-tx");
    stores.push(store);
    await expect(store.transaction(async () => {
      await store.setCursor("f", 42);
      throw new Error("boom");
    })).rejects.toThrow("boom");
    expect(await store.getCursor("f")).toBe(0);
  });
});
