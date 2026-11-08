/**
 * Sync orchestration for the web app (OFFLINE_SYNC.md §4.1): one sync loop per browser
 * (Web Locks), triggered at start, when the network returns, every minute and shortly
 * after each local change.
 */

import type { EnqueueInput, OpStatus, SyncEngine, SyncReport, SyncStore } from "@fms/sync-core";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { localSyncErrorNotification, syncNotifications } from "@fms/shared";

import { useNotifications } from "../notifications/NotificationsContext";

export interface SyncState {
  engine: SyncEngine;
  farmId: string;
  stats: Record<OpStatus, number>;
  online: boolean;
  syncing: boolean;
  lastReport: SyncReport | null;
  lastSyncAt: Date | null;
  /** Incremented whenever local data may have changed: views re-read the store. */
  revision: number;
  syncNow: () => Promise<void>;
  record: (input: Omit<EnqueueInput, "farmId">) => Promise<string>;
  refresh: () => void;
}

const SyncContext = createContext<SyncState | null>(null);
const EMPTY_STATS: Record<OpStatus, number> = {
  pending: 0, syncing: 0, synced: 0, failed: 0, conflict: 0,
};
const PERIOD_MS = 60_000;
const DEBOUNCE_MS = 2_000;

async function withBrowserLock(fn: () => Promise<void>): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    // ifAvailable: another tab is already syncing, skip this round.
    await navigator.locks.request("fms-sync", { ifAvailable: true }, async (lock) => {
      if (lock) await fn();
    });
    return;
  }
  await fn();
}

async function taskIds(engine: SyncEngine, farmId: string): Promise<Set<string>> {
  const views = await engine.view(farmId, "tasks.task");
  return new Set(views.filter((v) => !v.deleted).map((v) => v.entityId));
}

export function SyncProvider(props: {
  engine: SyncEngine;
  store: SyncStore;
  farmId: string;
  onAuthRequired: () => void;
  children: ReactNode;
}): ReactNode {
  const { engine, store, farmId, onAuthRequired } = props;
  const { notify } = useNotifications();
  const hadSynced = useRef(false);
  const [stats, setStats] = useState(EMPTY_STATS);
  const [online, setOnline] = useState(typeof navigator === "undefined" || navigator.onLine);
  const [syncing, setSyncing] = useState(false);
  const [lastReport, setLastReport] = useState<SyncReport | null>(null);
  const [lastSyncAt, setLastSyncAt] = useState<Date | null>(null);
  const [revision, setRevision] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(() => {
    void engine.stats(farmId).then(setStats);
    setRevision((value) => value + 1);
  }, [engine, farmId]);

  const syncNow = useCallback(async () => {
    setSyncing(true);
    try {
      await withBrowserLock(async () => {
        const before = await taskIds(engine, farmId);
        const report = await engine.sync(farmId);
        setLastReport(report);
        setOnline(!report.offline);
        if (!report.offline) setLastSyncAt(new Date());
        if (report.authRequired) onAuthRequired();
        // A first download onto an empty device is not "news": only later additions are.
        const firstLoad = !hadSynced.current && before.size === 0;
        if (!report.offline) hadSynced.current = true;
        const after = report.pulled > 0 ? await taskIds(engine, farmId) : before;
        const newTaskCount = firstLoad ? 0 : [...after].filter((id) => !before.has(id)).length;
        for (const n of syncNotifications({ farmId, report, operations: await store.listOperations(farmId),
                                            newTaskCount })) {
          notify(n);
        }
      });
    } catch (error) {
      // Local failure (e.g. IndexedDB): callers fire and forget, so report it here, visibly.
      console.error("Synchronisation impossible", error);
      notify(localSyncErrorNotification(farmId, error));
    } finally {
      setSyncing(false);
      refresh();
    }
  }, [engine, store, farmId, onAuthRequired, refresh, notify]);

  const record = useCallback(
    async (input: Omit<EnqueueInput, "farmId">) => {
      const opId = await engine.enqueue({ ...input, farmId });
      refresh();
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void syncNow(), DEBOUNCE_MS);
      return opId;
    },
    [engine, farmId, refresh, syncNow],
  );

  useEffect(() => {
    void syncNow();
    const onOnline = () => {
      setOnline(true);
      void syncNow();
    };
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    const interval = setInterval(() => void syncNow(), PERIOD_MS);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      clearInterval(interval);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [syncNow]);

  const value = useMemo<SyncState>(
    () => ({ engine, farmId, stats, online, syncing, lastReport, lastSyncAt, revision,
             syncNow, record, refresh }),
    [engine, farmId, stats, online, syncing, lastReport, lastSyncAt, revision, syncNow,
     record, refresh],
  );
  return <SyncContext.Provider value={value}>{props.children}</SyncContext.Provider>;
}

export function useSync(): SyncState {
  const value = useContext(SyncContext);
  if (!value) throw new Error("useSync must be used inside <SyncProvider>");
  return value;
}

/** Local view (server state + pending local changes) of an entity type. */
export function useLocalEntities<T>(entityType: string): { rows: (T & LocalMeta)[]; loading: boolean } {
  const { engine, farmId, revision } = useSync();
  const [rows, setRows] = useState<(T & LocalMeta)[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    void engine.view(farmId, entityType).then((views) => {
      if (!active) return;
      setRows(views.filter((v) => !v.deleted).map((v) => ({
        ...(v.data as T), _local: v.local, _version: v.version, _id: v.entityId })));
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [engine, farmId, entityType, revision]);
  return { rows, loading };
}

export interface LocalMeta {
  _local: OpStatus | null;
  _version: number;
  _id: string;
}
