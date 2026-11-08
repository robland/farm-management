/**
 * Sync orchestration for the web app (OFFLINE_SYNC.md §4.1): one sync loop per browser
 * (Web Locks), triggered at start, when the network returns, every minute and shortly
 * after each local change.
 */

import type { EnqueueInput, OpStatus, SyncEngine, SyncReport } from "@fms/sync-core";
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

export function SyncProvider(props: {
  engine: SyncEngine;
  farmId: string;
  onAuthRequired: () => void;
  children: ReactNode;
}): ReactNode {
  const { engine, farmId, onAuthRequired } = props;
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
        const report = await engine.sync(farmId);
        setLastReport(report);
        setOnline(!report.offline);
        if (!report.offline) setLastSyncAt(new Date());
        if (report.authRequired) onAuthRequired();
      });
    } finally {
      setSyncing(false);
      refresh();
    }
  }, [engine, farmId, onAuthRequired, refresh]);

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
