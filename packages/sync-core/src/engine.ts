/**
 * Storage-agnostic sync engine (docs/architecture/OFFLINE_SYNC.md).
 *
 * Guarantees:
 * - A local operation is never removed before the server confirmed it AND the
 *   confirmed state has been pulled back (or the user explicitly abandons it).
 * - An interrupted push (crash while "syncing") is retried: the server's
 *   idempotency on op_id makes the replay harmless.
 * - Successive updates of the same descriptive entity are compacted; financial
 *   operations and events are never compacted nor merged.
 */

import {
  AuthError,
  CursorExpiredError,
  type EntityRecord,
  type LocalOperation,
  NetworkError,
  type OpStatus,
  type OpType,
  type PushOperation,
  type PushResult,
  type SyncStore,
  type Transport,
} from "./types";

export interface EngineOptions {
  deviceId: string;
  authorId: string;
  batchSize?: number;
  pullLimit?: number;
  now?: () => number;
  newId?: () => string;
}

export interface EnqueueInput {
  farmId: string;
  opType: OpType;
  entityType: string;
  entityId: string;
  payload?: Record<string, unknown>;
  baseVersion?: number | null;
  baseValues?: Record<string, unknown>;
  command?: string;
  dependsOn?: string[];
}

export interface SyncReport {
  pushed: number;
  applied: number;
  conflicts: number;
  failed: number;
  pulled: number;
  offline: boolean;
  authRequired: boolean;
}

/** Entity types whose operations must never be merged locally. */
export const NEVER_COMPACT_PREFIXES = ["finance."];
const BACKOFF_BASE_MS = 2_000;
const BACKOFF_MAX_MS = 5 * 60_000;
const LOCAL_STATUSES: OpStatus[] = ["pending", "syncing", "failed", "conflict"];

export function backoffMs(attempts: number): number {
  return Math.min(BACKOFF_BASE_MS * 2 ** Math.max(0, attempts - 1), BACKOFF_MAX_MS);
}

export class SyncEngine {
  private readonly batchSize: number;
  private readonly pullLimit: number;
  private readonly now: () => number;
  private readonly newId: () => string;

  constructor(
    private readonly store: SyncStore,
    private readonly transport: Transport,
    private readonly options: EngineOptions,
  ) {
    this.batchSize = options.batchSize ?? 100;
    this.pullLimit = options.pullLimit ?? 500;
    this.now = options.now ?? (() => Date.now());
    this.newId = options.newId ?? (() => crypto.randomUUID());
  }

  /** Record a local change. Returns the operation id (idempotency key). */
  async enqueue(input: EnqueueInput): Promise<string> {
    return this.store.transaction(async () => {
      const compactable =
        input.opType === "update" &&
        !NEVER_COMPACT_PREFIXES.some((prefix) => input.entityType.startsWith(prefix));
      if (compactable) {
        const ops = await this.store.listOperations(input.farmId);
        const previous = ops.find(
          (op) =>
            op.status === "pending" &&
            (op.opType === "update" || op.opType === "create") &&
            op.entityType === input.entityType &&
            op.entityId === input.entityId,
        );
        if (previous?.opType === "create") {
          // Not yet on the server: fold the change into the pending creation.
          await this.store.updateOperation(previous.opId, {
            payload: { ...previous.payload, ...input.payload },
          });
          return previous.opId;
        }
        if (previous) {
          // Keep the OLDEST base: the server must compare against what this device last saw.
          const baseValues = { ...input.baseValues, ...previous.baseValues };
          await this.store.updateOperation(previous.opId, {
            payload: { ...previous.payload, ...input.payload },
            baseValues,
          });
          return previous.opId;
        }
      }
      const op: LocalOperation = {
        opId: this.newId(),
        opType: input.opType,
        entityType: input.entityType,
        entityId: input.entityId,
        farmId: input.farmId,
        payload: input.payload ?? {},
        baseVersion: input.baseVersion ?? null,
        baseValues: input.baseValues ?? {},
        authorId: this.options.authorId,
        deviceId: this.options.deviceId,
        createdAt: new Date(this.now()).toISOString(),
        version: 1,
        status: "pending",
        attempts: 0,
        ...(input.command ? { command: input.command } : {}),
        ...(input.dependsOn ? { dependsOn: input.dependsOn } : {}),
      };
      await this.store.addOperation(op);
      return op.opId;
    });
  }

  /** After a crash, operations left "syncing" go back to "pending" (safe: server is idempotent). */
  async recoverInterrupted(farmId: string): Promise<number> {
    const ops = await this.store.listOperations(farmId);
    const interrupted = ops.filter((op) => op.status === "syncing");
    for (const op of interrupted) {
      await this.store.updateOperation(op.opId, { status: "pending" });
    }
    return interrupted.length;
  }

  /** Put a failed or conflicting operation back in the queue (after a user correction). */
  async retry(opId: string, farmId: string, patch: Partial<LocalOperation> = {}): Promise<void> {
    const op = (await this.store.listOperations(farmId)).find((o) => o.opId === opId);
    if (!op || (op.status !== "failed" && op.status !== "conflict")) {
      throw new Error("Only failed or conflicting operations can be retried.");
    }
    await this.store.updateOperation(opId, {
      ...patch,
      status: "pending",
      attempts: 0,
      nextAttemptAt: 0,
    });
  }

  /** Explicit user decision to drop an operation that the server will never accept. */
  async abandon(opId: string, farmId: string): Promise<LocalOperation> {
    const op = (await this.store.listOperations(farmId)).find((o) => o.opId === opId);
    if (!op || (op.status !== "failed" && op.status !== "conflict")) {
      throw new Error("Only failed or conflicting operations can be abandoned.");
    }
    await this.store.removeOperation(opId);
    return op;
  }

  async push(farmId: string, report: SyncReport): Promise<void> {
    const now = this.now();
    const ops = (await this.store.listOperations(farmId))
      .filter((op) => op.status === "pending" && (op.nextAttemptAt ?? 0) <= now)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    for (let start = 0; start < ops.length; start += this.batchSize) {
      const batch = ops.slice(start, start + this.batchSize);
      for (const op of batch) {
        await this.store.updateOperation(op.opId, { status: "syncing" });
      }
      let results: PushResult[];
      try {
        results = await this.transport.push(this.options.deviceId, batch.map(toWire));
      } catch (error) {
        for (const op of batch) {
          await this.store.updateOperation(op.opId, {
            status: "pending",
            attempts: op.attempts + 1,
            nextAttemptAt: now + backoffMs(op.attempts + 1),
          });
        }
        if (error instanceof NetworkError) {
          report.offline = true;
          return;
        }
        if (error instanceof AuthError) {
          report.authRequired = true;
          return;
        }
        throw error;
      }
      report.pushed += batch.length;
      const byId = new Map(results.map((result) => [result.op_id, result]));
      for (const op of batch) {
        const result = byId.get(op.opId);
        if (!result) {
          await this.store.updateOperation(op.opId, { status: "pending" });
          continue;
        }
        await this.applyResult(op, result, now, report);
      }
    }
  }

  private async applyResult(
    op: LocalOperation,
    result: PushResult,
    now: number,
    report: SyncReport,
  ): Promise<void> {
    if (result.status === "applied") {
      report.applied += 1;
      await this.store.updateOperation(op.opId, {
        status: "synced",
        serverResult:
          result.entity_version !== undefined ? { entityVersion: result.entity_version } : {},
      });
    } else if (result.status === "conflict") {
      report.conflicts += 1;
      await this.store.updateOperation(op.opId, {
        status: "conflict",
        ...(result.conflict_id ? { conflictId: result.conflict_id } : {}),
      });
    } else {
      const error = result.error ?? { code: "unknown", message: "", retryable: false };
      if (error.retryable) {
        await this.store.updateOperation(op.opId, {
          status: "pending",
          attempts: op.attempts + 1,
          nextAttemptAt: now + backoffMs(op.attempts + 1),
          lastError: { code: error.code, message: error.message, retryable: true },
        });
      } else {
        report.failed += 1;
        await this.store.updateOperation(op.opId, {
          status: "failed",
          lastError: {
            code: error.code,
            message: error.message,
            retryable: false,
            fieldErrors: error.field_errors,
          },
        });
      }
    }
  }

  async pull(farmId: string, report: SyncReport): Promise<void> {
    let cursor = await this.store.getCursor(farmId);
    for (;;) {
      let page;
      try {
        page = await this.transport.pull(farmId, cursor, this.pullLimit);
      } catch (error) {
        if (error instanceof CursorExpiredError) {
          // Full reload of server data; the local outbox is left untouched.
          await this.store.transaction(async () => {
            await this.store.purgeEntityTypes(farmId, "*");
            await this.store.setCursor(farmId, 0);
          });
          cursor = 0;
          continue;
        }
        if (error instanceof NetworkError) {
          report.offline = true;
          return;
        }
        if (error instanceof AuthError) {
          report.authRequired = true;
          return;
        }
        throw error;
      }
      // The page and its cursor are committed together: an interruption replays the page.
      await this.store.transaction(async () => {
        const upserts: EntityRecord[] = [];
        for (const change of page.changes) {
          if (change.operation === "delete") {
            await this.store.deleteEntity(change.entity_type, change.entity_id);
          } else {
            upserts.push({
              entityType: change.entity_type,
              entityId: change.entity_id,
              farmId,
              version: change.version,
              data: change.data ?? {},
            });
          }
        }
        await this.store.putEntities(upserts);
        if (page.purge.length) {
          await this.store.purgeEntityTypes(farmId, page.purge);
        }
        await this.store.setCursor(farmId, page.next_cursor);
      });
      report.pulled += page.changes.length;
      cursor = page.next_cursor;
      if (!page.has_more) {
        return;
      }
    }
  }

  /** Drop synced operations once the confirmed server state is stored locally. */
  async cleanup(farmId: string): Promise<number> {
    let removed = 0;
    for (const op of await this.store.listOperations(farmId)) {
      if (op.status !== "synced") {
        continue;
      }
      const confirmedVersion = op.serverResult?.entityVersion;
      const local = await this.store.getEntity(op.entityType, op.entityId);
      const received =
        confirmedVersion === undefined ||
        (local !== undefined && local.version >= confirmedVersion) ||
        (op.opType === "delete" && local === undefined);
      if (received) {
        await this.store.removeOperation(op.opId);
        removed += 1;
      }
    }
    return removed;
  }

  /** One full cycle: recover, push, pull, cleanup. */
  async sync(farmId: string): Promise<SyncReport> {
    const report: SyncReport = {
      pushed: 0,
      applied: 0,
      conflicts: 0,
      failed: 0,
      pulled: 0,
      offline: false,
      authRequired: false,
    };
    await this.recoverInterrupted(farmId);
    await this.push(farmId, report);
    if (!report.offline && !report.authRequired) {
      await this.pull(farmId, report);
      await this.cleanup(farmId);
    }
    return report;
  }

  /**
   * Entities as the user should see them: last server state + local operations not yet
   * confirmed, in order (OFFLINE_SYNC.md §2.3).
   */
  async view(farmId: string, entityType: string): Promise<LocalView[]> {
    const rows = new Map<string, LocalView>();
    for (const record of await this.store.listEntities(farmId, entityType)) {
      rows.set(record.entityId, { ...record, data: { ...record.data }, local: null });
    }
    const ops = (await this.store.listOperations(farmId))
      .filter((op) => op.entityType === entityType && LOCAL_STATUSES.includes(op.status))
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    for (const op of ops) {
      const current = rows.get(op.entityId);
      if (op.opType === "create") {
        rows.set(op.entityId, {
          entityType,
          entityId: op.entityId,
          farmId,
          version: 0,
          data: { id: op.entityId, ...op.payload },
          local: op.status,
        });
      } else if (op.opType === "update" && current) {
        current.data = { ...current.data, ...op.payload };
        current.local = op.status;
      } else if (op.opType === "delete" && current) {
        current.local = op.status;
        current.deleted = true;
      }
    }
    return [...rows.values()];
  }

  async stats(farmId: string): Promise<Record<OpStatus, number>> {
    const counts: Record<OpStatus, number> = {
      pending: 0,
      syncing: 0,
      synced: 0,
      failed: 0,
      conflict: 0,
    };
    for (const op of await this.store.listOperations(farmId)) {
      counts[op.status] += 1;
    }
    return counts;
  }
}

export interface LocalView extends EntityRecord {
  /** Status of the latest local, not yet confirmed change (null = server state). */
  local: OpStatus | null;
  deleted?: boolean;
}

function toWire(op: LocalOperation): PushOperation {
  return {
    op_id: op.opId,
    farm_id: op.farmId,
    op_type: op.opType,
    ...(op.command ? { command: op.command } : {}),
    entity_type: op.entityType,
    entity_id: op.entityId,
    payload: op.payload,
    base_version: op.baseVersion,
    base_values: op.baseValues,
    created_at: op.createdAt,
    author_id: op.authorId,
    depends_on: op.dependsOn ?? [],
  };
}
