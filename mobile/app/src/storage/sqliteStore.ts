/**
 * SQLite storage implementing the sync-core SyncStore (OFFLINE_SYNC.md §2.2).
 *
 * Written against a minimal `SqlDatabase` interface matching expo-sqlite's
 * SQLiteDatabase (execAsync / runAsync / getAllAsync / getFirstAsync /
 * withTransactionAsync), so that it can be tested on Node with node:sqlite.
 */

import type { EntityRecord, LocalOperation, SyncStore } from "@fms/sync-core";

type Param = string | number | null;

export interface SqlDatabase {
  execAsync(source: string): Promise<void>;
  runAsync(source: string, params: Param[]): Promise<unknown>;
  getAllAsync<T>(source: string, params: Param[]): Promise<T[]>;
  getFirstAsync<T>(source: string, params: Param[]): Promise<T | null>;
  withTransactionAsync(task: () => Promise<void>): Promise<void>;
}

export const SCHEMA_VERSION = 1;

const MIGRATIONS: Record<number, string> = {
  1: `
    CREATE TABLE IF NOT EXISTS operations (
      op_id TEXT PRIMARY KEY NOT NULL,
      farm_id TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      body TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS operations_farm_status ON operations (farm_id, status);
    CREATE TABLE IF NOT EXISTS entities (
      entity_type TEXT NOT NULL,
      entity_id TEXT NOT NULL,
      farm_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      data TEXT NOT NULL,
      PRIMARY KEY (entity_type, entity_id)
    );
    CREATE INDEX IF NOT EXISTS entities_farm_type ON entities (farm_id, entity_type);
    CREATE TABLE IF NOT EXISTS cursors (
      farm_id TEXT PRIMARY KEY NOT NULL,
      cursor INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS kv (
      key TEXT PRIMARY KEY NOT NULL,
      value TEXT NOT NULL
    );
  `,
};

/** Versioned local schema migrations: the outbox must survive app updates. */
export async function migrate(db: SqlDatabase): Promise<void> {
  await db.execAsync("PRAGMA journal_mode = WAL;");
  const row = await db.getFirstAsync<{ user_version: number }>("PRAGMA user_version", []);
  let current = row?.user_version ?? 0;
  while (current < SCHEMA_VERSION) {
    current += 1;
    const sql = MIGRATIONS[current];
    if (!sql) throw new Error(`Missing local migration ${current}`);
    await db.execAsync(sql);
    await db.execAsync(`PRAGMA user_version = ${current}`);
  }
}

interface EntityRow {
  entity_type: string;
  entity_id: string;
  farm_id: string;
  version: number;
  data: string;
}

const toRecord = (row: EntityRow): EntityRecord => ({
  entityType: row.entity_type,
  entityId: row.entity_id,
  farmId: row.farm_id,
  version: row.version,
  data: JSON.parse(row.data) as Record<string, unknown>,
});

export class SqliteStore implements SyncStore {
  private depth = 0;

  constructor(private readonly db: SqlDatabase) {}

  async transaction<T>(fn: () => Promise<T>): Promise<T> {
    // expo-sqlite transactions cannot nest: inner calls join the outer transaction.
    if (this.depth > 0) return fn();
    let result!: T;
    this.depth += 1;
    try {
      await this.db.withTransactionAsync(async () => {
        result = await fn();
      });
    } finally {
      this.depth -= 1;
    }
    return result;
  }

  async addOperation(op: LocalOperation): Promise<void> {
    await this.db.runAsync(
      "INSERT INTO operations (op_id, farm_id, status, created_at, body) VALUES (?, ?, ?, ?, ?)",
      [op.opId, op.farmId, op.status, op.createdAt, JSON.stringify(op)],
    );
  }

  async updateOperation(opId: string, patch: Partial<LocalOperation>): Promise<void> {
    const row = await this.db.getFirstAsync<{ body: string }>(
      "SELECT body FROM operations WHERE op_id = ?", [opId]);
    if (!row) throw new Error(`Unknown operation ${opId}`);
    const op: LocalOperation = { ...(JSON.parse(row.body) as LocalOperation), ...patch };
    await this.db.runAsync("UPDATE operations SET status = ?, body = ? WHERE op_id = ?",
                           [op.status, JSON.stringify(op), opId]);
  }

  async removeOperation(opId: string): Promise<void> {
    await this.db.runAsync("DELETE FROM operations WHERE op_id = ?", [opId]);
  }

  /** Operations not yet confirmed by the server, all farms (warning before logout). */
  async countUnsent(): Promise<number> {
    const row = await this.db.getFirstAsync<{ n: number }>(
      "SELECT COUNT(*) AS n FROM operations WHERE status != 'synced'", []);
    return row?.n ?? 0;
  }

  async listOperations(farmId: string): Promise<LocalOperation[]> {
    const rows = await this.db.getAllAsync<{ body: string }>(
      "SELECT body FROM operations WHERE farm_id = ? ORDER BY created_at", [farmId]);
    return rows.map((row) => JSON.parse(row.body) as LocalOperation);
  }

  async putEntities(records: EntityRecord[]): Promise<void> {
    for (const r of records) {
      await this.db.runAsync(
        `INSERT INTO entities (entity_type, entity_id, farm_id, version, data) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT (entity_type, entity_id) DO UPDATE SET
           farm_id = excluded.farm_id, version = excluded.version, data = excluded.data`,
        [r.entityType, r.entityId, r.farmId, r.version, JSON.stringify(r.data)],
      );
    }
  }

  async deleteEntity(entityType: string, entityId: string): Promise<void> {
    await this.db.runAsync("DELETE FROM entities WHERE entity_type = ? AND entity_id = ?",
                           [entityType, entityId]);
  }

  async purgeEntityTypes(farmId: string, entityTypes: string[] | "*"): Promise<void> {
    if (entityTypes === "*") {
      await this.db.runAsync("DELETE FROM entities WHERE farm_id = ?", [farmId]);
      return;
    }
    for (const type of entityTypes) {
      await this.db.runAsync("DELETE FROM entities WHERE farm_id = ? AND entity_type = ?",
                             [farmId, type]);
    }
  }

  async getEntity(entityType: string, entityId: string): Promise<EntityRecord | undefined> {
    const row = await this.db.getFirstAsync<EntityRow>(
      "SELECT * FROM entities WHERE entity_type = ? AND entity_id = ?", [entityType, entityId]);
    return row ? toRecord(row) : undefined;
  }

  async listEntities(farmId: string, entityType: string): Promise<EntityRecord[]> {
    const rows = await this.db.getAllAsync<EntityRow>(
      "SELECT * FROM entities WHERE farm_id = ? AND entity_type = ?", [farmId, entityType]);
    return rows.map(toRecord);
  }

  /** Small app state (cached profile, selected farm) kept in the user's database. */
  async getValue<T>(key: string): Promise<T | null> {
    const row = await this.db.getFirstAsync<{ value: string }>(
      "SELECT value FROM kv WHERE key = ?", [key]);
    return row ? (JSON.parse(row.value) as T) : null;
  }

  async setValue(key: string, value: unknown): Promise<void> {
    await this.db.runAsync(
      "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
      [key, JSON.stringify(value)],
    );
  }

  async getCursor(farmId: string): Promise<number> {
    const row = await this.db.getFirstAsync<{ cursor: number }>(
      "SELECT cursor FROM cursors WHERE farm_id = ?", [farmId]);
    return row?.cursor ?? 0;
  }

  async setCursor(farmId: string, cursor: number): Promise<void> {
    await this.db.runAsync(
      "INSERT INTO cursors (farm_id, cursor) VALUES (?, ?) ON CONFLICT (farm_id) DO UPDATE SET cursor = excluded.cursor",
      [farmId, cursor],
    );
  }
}
