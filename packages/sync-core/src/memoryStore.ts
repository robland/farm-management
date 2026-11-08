import type { EntityRecord, LocalOperation, SyncStore } from "./types";

/** In-memory SyncStore (tests). `transaction` snapshots and restores on failure. */
export class MemoryStore implements SyncStore {
  operations = new Map<string, LocalOperation>();
  entities = new Map<string, EntityRecord>();
  cursors = new Map<string, number>();

  private key(entityType: string, entityId: string): string {
    return `${entityType}:${entityId}`;
  }

  async transaction<T>(fn: () => Promise<T>): Promise<T> {
    const snapshot = {
      operations: new Map([...this.operations].map(([k, v]) => [k, structuredClone(v)])),
      entities: new Map([...this.entities].map(([k, v]) => [k, structuredClone(v)])),
      cursors: new Map(this.cursors),
    };
    try {
      return await fn();
    } catch (error) {
      this.operations = snapshot.operations;
      this.entities = snapshot.entities;
      this.cursors = snapshot.cursors;
      throw error;
    }
  }

  async addOperation(op: LocalOperation): Promise<void> {
    this.operations.set(op.opId, structuredClone(op));
  }

  async updateOperation(opId: string, patch: Partial<LocalOperation>): Promise<void> {
    const op = this.operations.get(opId);
    if (!op) throw new Error(`Unknown operation ${opId}`);
    this.operations.set(opId, { ...op, ...structuredClone(patch) });
  }

  async removeOperation(opId: string): Promise<void> {
    this.operations.delete(opId);
  }

  async listOperations(farmId: string): Promise<LocalOperation[]> {
    return [...this.operations.values()]
      .filter((op) => op.farmId === farmId)
      .map((op) => structuredClone(op));
  }

  async putEntities(records: EntityRecord[]): Promise<void> {
    for (const record of records) {
      this.entities.set(this.key(record.entityType, record.entityId), structuredClone(record));
    }
  }

  async deleteEntity(entityType: string, entityId: string): Promise<void> {
    this.entities.delete(this.key(entityType, entityId));
  }

  async purgeEntityTypes(farmId: string, entityTypes: string[] | "*"): Promise<void> {
    for (const [key, record] of this.entities) {
      if (record.farmId === farmId && (entityTypes === "*" || entityTypes.includes(record.entityType))) {
        this.entities.delete(key);
      }
    }
  }

  async getEntity(entityType: string, entityId: string): Promise<EntityRecord | undefined> {
    const record = this.entities.get(this.key(entityType, entityId));
    return record ? structuredClone(record) : undefined;
  }

  async listEntities(farmId: string, entityType: string): Promise<EntityRecord[]> {
    return [...this.entities.values()]
      .filter((r) => r.farmId === farmId && r.entityType === entityType)
      .map((r) => structuredClone(r));
  }

  async getCursor(farmId: string): Promise<number> {
    return this.cursors.get(farmId) ?? 0;
  }

  async setCursor(farmId: string, cursor: number): Promise<void> {
    this.cursors.set(farmId, cursor);
  }
}
