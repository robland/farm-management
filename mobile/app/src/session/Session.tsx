/**
 * Session, local database and sync loop for the mobile app (OFFLINE_SYNC.md §4.1).
 *
 * - Secure store: refresh token, device id and current user id only (small values).
 * - The user's SQLite database: outbox, entities and a cached profile, so that the
 *   app opens offline (FR-110).
 * - Sync runs at start, when connectivity returns (NetInfo), every minute and two
 *   seconds after each local change. Background execution is never relied on.
 */

import NetInfo from "@react-native-community/netinfo";
import { AuthError, type EnqueueInput, NetworkError, type OpStatus, SyncEngine } from "@fms/sync-core";
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import * as SQLite from "expo-sqlite";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef,
         useState } from "react";

import { ApiClient } from "../api/client";
import { migrate, SqliteStore } from "../storage/sqliteStore";
import { HttpTransport } from "../sync/transport";

export interface MeFarm {
  id: string;
  name: string;
  organization_id: string;
  role: string | null;
  permissions: string[];
}

interface Me {
  user: { id: string; full_name: string };
  farms: MeFarm[];
}

interface SessionValue {
  api: ApiClient;
  me: Me | null;
  farm: MeFarm | null;
  ready: boolean;
  online: boolean;
  syncing: boolean;
  stats: Record<OpStatus, number>;
  lastSyncAt: Date | null;
  revision: number;
  /** Confirmation of the last local save, shown on the home screen after router.back(). */
  notice: string | null;
  flash: (message: string | null) => void;
  store: SqliteStore | null;
  engine: SyncEngine | null;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  pickFarm: (farm: MeFarm | null) => void;
  syncNow: () => Promise<void>;
  record: (input: Omit<EnqueueInput, "farmId">) => Promise<string>;
  refresh: () => void;
  can: (permission: string) => boolean;
}

const SessionContext = createContext<SessionValue | null>(null);
const USER_KEY = "fms.userId";
const EMPTY: Record<OpStatus, number> = { pending: 0, syncing: 0, synced: 0, failed: 0, conflict: 0 };
const baseUrl = String(Constants.expoConfig?.extra?.apiBaseUrl ?? "http://10.0.2.2:8000/api/v1");

async function openUserStore(userId: string): Promise<SqliteStore> {
  // One database per user: a shared phone never mixes data.
  const db = await SQLite.openDatabaseAsync(`fms-${userId}.db`);
  await migrate(db);
  return new SqliteStore(db);
}

export function SessionProvider({ children }: { children: ReactNode }): ReactNode {
  const api = useMemo(() => new ApiClient(baseUrl), []);
  const [me, setMe] = useState<Me | null>(null);
  const [farm, setFarm] = useState<MeFarm | null>(null);
  const [ready, setReady] = useState(false);
  const [online, setOnline] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [stats, setStats] = useState(EMPTY);
  const [revision, setRevision] = useState(0);
  const [store, setStore] = useState<SqliteStore | null>(null);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [lastSyncAt, setLastSyncAt] = useState<Date | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = useCallback((message: string | null) => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice(message);
    if (message) noticeTimer.current = setTimeout(() => setNotice(null), 6_000);
  }, []);

  const loadMe = useCallback(async (userStore: SqliteStore) => {
    try {
      const data = await api.request<Me>("GET", "/me/");
      setMe(data);
      await userStore.setValue("me", data);
    } catch (error) {
      if (error instanceof AuthError) setMe(null);
      else if (!(error instanceof NetworkError)) throw error; // offline: keep the cache
    }
  }, [api]);

  useEffect(() => {
    void (async () => {
      const userId = await SecureStore.getItemAsync(USER_KEY);
      if (userId && (await api.hasSession())) {
        const userStore = await openUserStore(userId);
        setStore(userStore);
        setDeviceId(await api.deviceId());
        const cached = await userStore.getValue<Me>("me");
        const lastFarm = await userStore.getValue<string>("farm");
        setMe(cached);
        setFarm(cached?.farms.find((f) => f.id === lastFarm) ?? null);
        await loadMe(userStore);
      }
      setReady(true);
    })();
  }, [api, loadMe]);

  const engine = useMemo(() => (store && me && deviceId && farm
    ? new SyncEngine(store, new HttpTransport(api), { deviceId, authorId: me.user.id })
    : null), [store, me?.user.id, deviceId, farm?.id, api]);

  const refresh = useCallback(() => {
    if (engine && farm) void engine.stats(farm.id).then(setStats);
    setRevision((value) => value + 1);
  }, [engine, farm]);

  const logout = useCallback(async () => {
    await api.logout();
    await SecureStore.deleteItemAsync(USER_KEY);
    setMe(null);
    setFarm(null);
    setStore(null);
  }, [api]);

  const syncNow = useCallback(async () => {
    if (!engine || !farm) return;
    setSyncing(true);
    try {
      const report = await engine.sync(farm.id);
      setOnline(!report.offline);
      if (!report.offline) setLastSyncAt(new Date());
      if (report.authRequired) await logout();
    } finally {
      setSyncing(false);
      refresh();
    }
  }, [engine, farm, logout, refresh]);

  const record = useCallback(async (input: Omit<EnqueueInput, "farmId">) => {
    if (!engine || !farm) throw new Error("Aucune exploitation sélectionnée.");
    const opId = await engine.enqueue({ ...input, farmId: farm.id });
    refresh();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void syncNow(), 2_000);
    return opId;
  }, [engine, farm, refresh, syncNow]);

  useEffect(() => {
    if (!engine) return;
    void syncNow();
    const unsubscribe = NetInfo.addEventListener((state) => {
      setOnline(Boolean(state.isConnected));
      if (state.isConnected) void syncNow();
    });
    const interval = setInterval(() => void syncNow(), 60_000);
    return () => {
      unsubscribe();
      clearInterval(interval);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [engine, syncNow]);

  const login = useCallback(async (identifier: string, password: string) => {
    const session = await api.login(identifier, password);
    await SecureStore.setItemAsync(USER_KEY, session.userId);
    const userStore = await openUserStore(session.userId);
    setStore(userStore);
    setDeviceId(session.deviceId);
    await loadMe(userStore);
  }, [api, loadMe]);

  const pickFarm = useCallback((picked: MeFarm | null) => {
    setFarm(picked);
    setLastSyncAt(null);
    if (store) void store.setValue("farm", picked?.id ?? null);
  }, [store]);

  // A single farm needs no picker.
  useEffect(() => {
    const only = me?.farms.length === 1 ? me.farms[0] : undefined;
    if (only && !farm) pickFarm(only);
  }, [me, farm, pickFarm]);

  const value = useMemo<SessionValue>(() => ({
    api, me, farm, ready, online, syncing, stats, lastSyncAt, revision, notice, flash, store, engine,
    login, logout, pickFarm, syncNow, record, refresh,
    can: (permission) => Boolean(farm?.permissions.includes(permission)),
  }), [api, me, farm, ready, online, syncing, stats, lastSyncAt, revision, notice, flash, store, engine,
       login, logout, pickFarm, syncNow, record, refresh]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

/** Local view (server state + pending changes) of an entity type for the current farm. */
export function useLocalEntities<T>(entityType: string): (T & { _id: string; _local: OpStatus | null })[] {
  const { engine, farm, revision } = useSession();
  const [rows, setRows] = useState<(T & { _id: string; _local: OpStatus | null })[]>([]);
  useEffect(() => {
    if (!engine || !farm) return;
    let active = true;
    void engine.view(farm.id, entityType).then((views) => {
      if (active) {
        setRows(views.filter((v) => !v.deleted).map((v) => ({
          ...(v.data as T), _id: v.entityId, _local: v.local })));
      }
    });
    return () => {
      active = false;
    };
  }, [engine, farm, entityType, revision]);
  return rows;
}
