/**
 * IndexedDB storage (Dexie) implementing the sync-core SyncStore
 * (OFFLINE_SYNC.md §2.1). One database per user isolates shared computers.
 */

import type { EntityRecord, LocalOperation, SyncStore } from "@fms/sync-core";
import Dexie, { type Table } from "dexie";

interface CursorRow {
  farmId: string;
  cursor: number;
}

class FmsDatabase extends Dexie {
  operations!: Table<LocalOperation, string>;
  entities!: Table<EntityRecord, [string, string]>;
  cursors!: Table<CursorRow, string>;

  constructor(name: string) {
    super(name);
    this.version(1).stores({
      operations: "opId, farmId, [farmId+status], createdAt, entityId",
      entities: "[entityType+entityId], farmId, [farmId+entityType]",
      cursors: "farmId",
    });
  }
}

export class DexieStore implements SyncStore {
  readonly db: FmsDatabase;

  constructor(userId: string) {
    this.db = new FmsDatabase(`fms-${userId}`);
  }

  transaction<T>(fn: () => Promise<T>): Promise<T> {
    // Dexie scopes nested calls to the same transaction automatically.
    return this.db.transaction("rw", this.db.operations, this.db.entities, this.db.cursors, fn);
  }

  async addOperation(op: LocalOperation): Promise<void> {
    await this.db.operations.add(op);
  }

  async updateOperation(opId: string, patch: Partial<LocalOperation>): Promise<void> {
    const updated = await this.db.operations.update(opId, patch);
    if (!updated && !(await this.db.operations.get(opId))) {
      throw new Error(`Unknown operation ${opId}`);
    }
  }

  async removeOperation(opId: string): Promise<void> {
    await this.db.operations.delete(opId);
  }

  listOperations(farmId: string): Promise<LocalOperation[]> {
    return this.db.operations.where("farmId").equals(farmId).toArray();
  }

  async putEntities(records: EntityRecord[]): Promise<void> {
    if (records.length) await this.db.entities.bulkPut(records);
  }

  async deleteEntity(entityType: string, entityId: string): Promise<void> {
    await this.db.entities.delete([entityType, entityId]);
  }

  async purgeEntityTypes(farmId: string, entityTypes: string[] | "*"): Promise<void> {
    const rows = this.db.entities.where("farmId").equals(farmId);
    if (entityTypes === "*") {
      await rows.delete();
    } else {
      await rows.filter((row) => entityTypes.includes(row.entityType)).delete();
    }
  }

  getEntity(entityType: string, entityId: string): Promise<EntityRecord | undefined> {
    return this.db.entities.get([entityType, entityId]);
  }

  listEntities(farmId: string, entityType: string): Promise<EntityRecord[]> {
    return this.db.entities.where("[farmId+entityType]").equals([farmId, entityType]).toArray();
  }

  async getCursor(farmId: string): Promise<number> {
    return (await this.db.cursors.get(farmId))?.cursor ?? 0;
  }

  async setCursor(farmId: string, cursor: number): Promise<void> {
    await this.db.cursors.put({ farmId, cursor });
  }
}

/** Ask the browser not to evict offline data (OFFLINE_SYNC.md §2.1). */
export async function requestPersistentStorage(): Promise<boolean> {
  if (!navigator.storage?.persist) return false;
  return (await navigator.storage.persisted()) || navigator.storage.persist();
}
