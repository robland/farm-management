/**
 * Session, local database and sync loop for the mobile app (OFFLINE_SYNC.md §4.1).
 *
 * - Secure store: refresh token, device id and current user id only (small values).
 * - The user's SQLite database: outbox, entities, a cached profile (so that the app
 *   opens offline, FR-110) and the notification history.
 * - Sync runs at start, when connectivity returns (NetInfo), every minute and two
 *   seconds after each local change. Background execution is never relied on.
 */

import NetInfo from "@react-native-community/netinfo";
import {
  addNotification,
  type AppNotification,
  localSyncErrorNotification,
  markAllRead as markAllReadList,
  markRead as markReadList,
  type NotificationInput,
  sanitizeNotifications,
  syncNotifications,
  unreadCount,
} from "@fms/shared";
import { AuthError, type EnqueueInput, NetworkError, type OpStatus, SyncEngine } from "@fms/sync-core";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
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
  is_org_admin?: boolean;
  permissions: string[];
}

export interface Me {
  user: { id: string; full_name: string; email?: string | null; phone?: string | null };
  organizations: { id: string; name: string; is_org_admin: boolean }[];
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
  store: SqliteStore | null;
  engine: SyncEngine | null;
  notifications: AppNotification[];
  unread: number;
  notify: (input: NotificationInput) => void;
  markAllRead: () => void;
  markRead: (id: string) => void;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Unsent operations of every farm, to warn before logging out. */
  countUnsent: () => Promise<number>;
  reloadProfile: () => Promise<void>;
  pickFarm: (farm: MeFarm | null) => void;
  syncNow: () => Promise<void>;
  record: (input: Omit<EnqueueInput, "farmId">) => Promise<string>;
  refresh: () => void;
  can: (permission: string) => boolean;
}

const SessionContext = createContext<SessionValue | null>(null);
const USER_KEY = "fms.userId";
const NOTIFICATIONS_KEY = "notifications";
const EMPTY: Record<OpStatus, number> = { pending: 0, syncing: 0, synced: 0, failed: 0, conflict: 0 };
const baseUrl = String(Constants.expoConfig?.extra?.apiBaseUrl ?? "http://10.0.2.2:8000/api/v1");

async function openUserStore(userId: string): Promise<SqliteStore> {
  // One database per user: a shared phone never mixes data.
  const db = await SQLite.openDatabaseAsync(`fms-${userId}.db`);
  await migrate(db);
  return new SqliteStore(db);
}

async function taskIds(engine: SyncEngine, farmId: string): Promise<Set<string>> {
  const views = await engine.view(farmId, "tasks.task");
  return new Set(views.filter((v) => !v.deleted).map((v) => v.entityId));
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
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const notificationsLoaded = useRef(false);
  const hadSynced = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Notification history: loaded with the user's database, saved on every change.
  useEffect(() => {
    notificationsLoaded.current = false;
    setNotifications([]);
    if (!store) return;
    let active = true;
    void store.getValue<unknown>(NOTIFICATIONS_KEY).then((saved) => {
      if (!active) return;
      // Keep what was notified while loading.
      setNotifications((current) => [...current, ...sanitizeNotifications(saved)]);
      notificationsLoaded.current = true;
    });
    return () => {
      active = false;
    };
  }, [store]);

  useEffect(() => {
    if (store && notificationsLoaded.current) void store.setValue(NOTIFICATIONS_KEY, notifications);
  }, [store, notifications]);

  const notify = useCallback((input: NotificationInput) => {
    setNotifications((list) => addNotification(list, input, new Date(), () => Crypto.randomUUID()));
  }, []);
  const markAllRead = useCallback(() => setNotifications(markAllReadList), []);
  const markRead = useCallback((id: string) => setNotifications((list) => markReadList(list, id)), []);

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

  const countUnsent = useCallback(async () => (store ? store.countUnsent() : 0), [store]);

  const reloadProfile = useCallback(async () => {
    if (store) await loadMe(store);
  }, [store, loadMe]);

  const syncNow = useCallback(async () => {
    if (!engine || !farm || !store) return;
    setSyncing(true);
    try {
      const before = await taskIds(engine, farm.id);
      const report = await engine.sync(farm.id);
      setOnline(!report.offline);
      if (!report.offline) setLastSyncAt(new Date());
      if (report.authRequired) await logout();
      // A first download onto an empty phone is not "news": only later additions are.
      const firstLoad = !hadSynced.current && before.size === 0;
      if (!report.offline) hadSynced.current = true;
      const after = report.pulled > 0 ? await taskIds(engine, farm.id) : before;
      const newTaskCount = firstLoad ? 0 : [...after].filter((id) => !before.has(id)).length;
      for (const n of syncNotifications({ farmId: farm.id, report,
                                          operations: await store.listOperations(farm.id), newTaskCount })) {
        notify(n);
      }
    } catch (error) {
      // Local failure (e.g. SQLite): callers fire and forget, so report it here, visibly.
      console.error("Synchronisation impossible", error);
      notify(localSyncErrorNotification(farm.id, error));
    } finally {
      setSyncing(false);
      refresh();
    }
  }, [engine, farm, store, logout, refresh, notify]);

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
    hadSynced.current = false;
    if (store) void store.setValue("farm", picked?.id ?? null);
  }, [store]);

  // A single farm needs no picker.
  useEffect(() => {
    const only = me?.farms.length === 1 ? me.farms[0] : undefined;
    if (only && !farm) pickFarm(only);
  }, [me, farm, pickFarm]);

  const value = useMemo<SessionValue>(() => ({
    api, me, farm, ready, online, syncing, stats, lastSyncAt, revision, store, engine,
    notifications, unread: unreadCount(notifications), notify, markAllRead, markRead,
    login, logout, countUnsent, reloadProfile, pickFarm, syncNow, record, refresh,
    can: (permission) => Boolean(farm?.permissions.includes(permission)),
  }), [api, me, farm, ready, online, syncing, stats, lastSyncAt, revision, store, engine, notifications,
       notify, markAllRead, markRead, login, logout, countUnsent, reloadProfile, pickFarm, syncNow, record,
       refresh]);

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
