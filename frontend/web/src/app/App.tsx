import { AuthError, NetworkError, SyncEngine } from "@fms/sync-core";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { ApiClient } from "../api/client";
import type { Me, MeFarm } from "../api/types";
import { LoginPage } from "../features/auth/LoginPage";
import { FarmPicker } from "../features/farms/FarmPicker";
import { ExpensesPage } from "../features/finance/ExpensesPage";
import { ParcelsPage } from "../features/parcels/ParcelsPage";
import { SyncPage } from "../features/sync/SyncPage";
import { TasksPage } from "../features/tasks/TasksPage";
import { DexieStore, requestPersistentStorage } from "../storage/dexieStore";
import { SyncProvider, useSync } from "../sync/SyncContext";
import { HttpTransport } from "../sync/transport";
import { Button, ConfirmDialog, ErrorMessage, Loading, OfflineBanner, SyncBadge } from "../ui/components";

const ME_CACHE = "fms.me";
const FARM_KEY = "fms.farm";
const TAB_KEY = "fms.tab";

type Tab = "parcels" | "tasks" | "expenses" | "sync";

/** Remembered tab: a convenience only, so storage failures are ignored. */
function readTab(): string | null {
  try {
    return sessionStorage.getItem(TAB_KEY);
  } catch {
    return null;
  }
}

function Shell(props: { farm: MeFarm; userName: string; store: DexieStore; api: ApiClient;
                        canSwitchFarm: boolean; onSwitchFarm: () => void; onLogout: () => void }): ReactNode {
  const { online, syncing, stats } = useSync();
  const can = (code: string) => props.farm.permissions.includes(code);
  const problems = stats.failed + stats.conflict;
  const unsent = stats.pending + stats.syncing + problems;
  const tabs: { id: Tab; label: string; visible: boolean; badge?: number }[] = [
    { id: "tasks", label: "Tâches", visible: can("tasks.view") },
    { id: "parcels", label: "Parcelles", visible: can("fields.view") },
    { id: "expenses", label: "Dépenses", visible: can("finance.view") || can("finance.transaction.create") },
    { id: "sync", label: "Synchronisation", visible: true, badge: problems },
  ];
  const visible = tabs.filter((t) => t.visible);
  const [tab, setTabState] = useState<Tab>(() => {
    const saved = readTab();
    return visible.find((t) => t.id === saved)?.id ?? visible[0]?.id ?? "sync";
  });
  const [confirmLogout, setConfirmLogout] = useState(false);

  const setTab = (next: Tab) => {
    setTabState(next);
    try {
      sessionStorage.setItem(TAB_KEY, next);
    } catch {
      // ignored: see readTab
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-stone-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold">{props.farm.name}</h1>
            <p className="flex flex-wrap items-center gap-x-2 text-sm text-stone-600">
              <span>{props.userName}</span>
              {props.canSwitchFarm && (
                <button type="button" className="text-green-800 underline" onClick={props.onSwitchFarm}>
                  Changer d'exploitation
                </button>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <SyncBadge online={online} syncing={syncing} stats={stats} />
            <Button variant="secondary"
                    onClick={() => (unsent ? setConfirmLogout(true) : props.onLogout())}>
              Déconnexion
            </Button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-4xl gap-1 overflow-x-auto px-4" aria-label="Sections">
          {visible.map((t) => (
            <button key={t.id} type="button" aria-current={t.id === tab ? "page" : undefined}
                    onClick={() => setTab(t.id)}
                    className={`inline-flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium
                                focus-visible:outline-2 focus-visible:outline-green-700 ${t.id === tab
                                  ? "border-green-700 text-green-800"
                                  : "border-transparent text-stone-600 hover:text-stone-900"}`}>
              {t.label}
              {t.badge ? (
                <span className="rounded-full bg-red-700 px-1.5 text-xs text-white">
                  {t.badge}<span className="sr-only"> à traiter</span>
                </span>
              ) : null}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4">
        <OfflineBanner online={online} />
        {tab === "parcels" && <ParcelsPage canEdit={can("fields.edit")} />}
        {tab === "tasks" && <TasksPage canReport={can("tasks.report")} />}
        {tab === "expenses" && (
          <ExpensesPage api={props.api} organizationId={props.farm.organization_id}
                        canCreate={can("finance.transaction.create")} />
        )}
        {tab === "sync" && <SyncPage store={props.store} />}
      </main>
      <ConfirmDialog open={confirmLogout} title="Se déconnecter ?" confirmLabel="Se déconnecter"
                     onCancel={() => setConfirmLogout(false)} onConfirm={props.onLogout}>
        Saisies pas encore envoyées au serveur : <strong>{unsent}</strong>. Elles restent sur cet appareil
        et seront envoyées à votre prochaine connexion avec ce même compte.
      </ConfirmDialog>
    </div>
  );
}

export function App({ api = new ApiClient() }: { api?: ApiClient }): ReactNode {
  const [me, setMe] = useState<Me | null>(() => {
    const cached = localStorage.getItem(ME_CACHE);
    return cached && api.hasRefreshToken ? (JSON.parse(cached) as Me) : null;
  });
  const [farmId, setFarmId] = useState<string | null>(() => localStorage.getItem(FARM_KEY));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadMe = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.request<Me>("GET", "/me/");
      setMe(data);
      localStorage.setItem(ME_CACHE, JSON.stringify(data));
      setError(null);
    } catch (err) {
      if (err instanceof AuthError) setMe(null);
      // Offline: keep the cached profile so the app stays usable (FR-110).
      else if (!(err instanceof NetworkError)) setError("Impossible de charger le profil.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (api.hasRefreshToken) void loadMe();
    void requestPersistentStorage();
  }, [api, loadMe]);

  const logout = useCallback(() => {
    api.logout();
    localStorage.removeItem(ME_CACHE);
    setMe(null);
  }, [api]);

  const pick = useCallback((picked: MeFarm) => {
    localStorage.setItem(FARM_KEY, picked.id);
    setFarmId(picked.id);
  }, []);

  // A single farm needs no picker.
  const onlyFarm = me?.farms.length === 1 ? me.farms[0] : undefined;
  const farm = me?.farms.find((f) => f.id === farmId) ?? onlyFarm ?? null;
  const store = useMemo(() => (me ? new DexieStore(me.user.id) : null), [me?.user.id]);
  const engine = useMemo(() => {
    const deviceId = api.deviceId();
    if (!store || !me || !deviceId) return null;
    return new SyncEngine(store, new HttpTransport(api), { deviceId, authorId: me.user.id });
  }, [store, me?.user.id, api]);

  if (!me) {
    return loading ? <Loading /> : <LoginPage api={api} onLoggedIn={() => void loadMe()} />;
  }
  if (!farm || !engine || !store) {
    return (
      <>
        {error && <div className="mx-auto max-w-md p-4"><ErrorMessage>{error}</ErrorMessage></div>}
        <FarmPicker me={me} onPick={pick} onLogout={logout} />
      </>
    );
  }
  return (
    <SyncProvider key={farm.id} engine={engine} farmId={farm.id} onAuthRequired={logout}>
      <Shell farm={farm} userName={me.user.full_name} store={store} api={api} onLogout={logout}
             canSwitchFarm={me.farms.length > 1} onSwitchFarm={() => setFarmId(null)} />
    </SyncProvider>
  );
}
