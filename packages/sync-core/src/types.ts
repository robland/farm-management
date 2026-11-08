/**
 * Offline-first operation queue types (docs/architecture/OFFLINE_SYNC.md §3, §4).
 */

export type OpStatus = "pending" | "syncing" | "synced" | "failed" | "conflict";
export type OpType = "create" | "update" | "delete" | "command";

export interface OperationError {
  code: string;
  message: string;
  retryable: boolean;
  fieldErrors?: unknown;
}

export interface LocalOperation {
  /** UUID, also the idempotency key on the server. */
  opId: string;
  opType: OpType;
  command?: string;
  entityType: string;
  entityId: string;
  farmId: string;
  /** Changed fields only (update) or the full object (create). */
  payload: Record<string, unknown>;
  /** Server version the operation was built on. */
  baseVersion: number | null;
  /** Base values of the changed fields (three-way merge on the server). */
  baseValues: Record<string, unknown>;
  authorId: string;
  deviceId: string;
  createdAt: string;
  version: 1;
  status: OpStatus;
  attempts: number;
  nextAttemptAt?: number;
  lastError?: OperationError;
  dependsOn?: string[];
  conflictId?: string;
  serverResult?: { entityVersion?: number };
}

export interface EntityRecord {
  entityType: string;
  entityId: string;
  farmId: string;
  version: number;
  data: Record<string, unknown>;
}

/** Storage adapter: Dexie (web), SQLite (mobile), memory (tests). */
export interface SyncStore {
  /** Run `fn` atomically: an entity change and its operation are written together. */
  transaction<T>(fn: () => Promise<T>): Promise<T>;
  addOperation(op: LocalOperation): Promise<void>;
  updateOperation(opId: string, patch: Partial<LocalOperation>): Promise<void>;
  removeOperation(opId: string): Promise<void>;
  listOperations(farmId: string): Promise<LocalOperation[]>;
  putEntities(records: EntityRecord[]): Promise<void>;
  deleteEntity(entityType: string, entityId: string): Promise<void>;
  purgeEntityTypes(farmId: string, entityTypes: string[] | "*"): Promise<void>;
  getEntity(entityType: string, entityId: string): Promise<EntityRecord | undefined>;
  listEntities(farmId: string, entityType: string): Promise<EntityRecord[]>;
  getCursor(farmId: string): Promise<number>;
  setCursor(farmId: string, cursor: number): Promise<void>;
}

// --- Wire protocol (backend apps/synchronization) ------------------------------------

export interface PushOperation {
  op_id: string;
  farm_id: string;
  op_type: OpType;
  command?: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  base_version: number | null;
  base_values: Record<string, unknown>;
  created_at: string;
  author_id: string;
  depends_on: string[];
}

export interface PushResult {
  op_id: string;
  status: "applied" | "rejected" | "conflict";
  entity_version?: number;
  conflict_id?: string;
  conflict_type?: string;
  error?: { code: string; message: string; retryable: boolean; field_errors?: unknown };
}

export interface PullChange {
  seq: number;
  entity_type: string;
  entity_id: string;
  operation: "upsert" | "delete";
  version: number;
  data?: Record<string, unknown>;
}

export interface PullResponse {
  changes: PullChange[];
  next_cursor: number;
  has_more: boolean;
  purge: string[];
  server_seq: number;
}

export class NetworkError extends Error {
  override name = "NetworkError";
}

export class AuthError extends Error {
  override name = "AuthError";
}

export class CursorExpiredError extends Error {
  override name = "CursorExpiredError";
}

export interface Transport {
  push(deviceId: string, operations: PushOperation[]): Promise<PushResult[]>;
  pull(farmId: string, cursor: number, limit: number): Promise<PullResponse>;
}
