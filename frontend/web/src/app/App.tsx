import { type NotificationTarget, roleLabel } from "@fms/shared";
import { AuthError, NetworkError, SyncEngine } from "@fms/sync-core";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { ApiClient } from "../api/client";
import type { Me, MeFarm } from "../api/types";
import { LoginPage } from "../features/auth/LoginPage";
import { CampaignsPage } from "../features/campaigns/CampaignsPage";
import { FarmPicker } from "../features/farms/FarmPicker";
import { FinancePage } from "../features/finance/FinancePage";
import { ParcelsPage } from "../features/parcels/ParcelsPage";
import { SyncPage } from "../features/sync/SyncPage";
import { TasksPage } from "../features/tasks/TasksPage";
import { NotificationsProvider } from "../notifications/NotificationsContext";
import { DexieStore, requestPersistentStorage } from "../storage/dexieStore";
import { SyncProvider, useSync } from "../sync/SyncContext";
import { HttpTransport } from "../sync/transport";
import { ConfirmDialog, ErrorMessage, Loading, OfflineBanner, SyncBadge } from "../ui/components";
import { AppHeader } from "./AppHeader";

const ME_CACHE = "fms.me";
const FARM_KEY = "fms.farm";
const TAB_KEY = "fms.tab";

type Tab = NotificationTarget;

/** Remembered tab: a convenience only, so storage failures are ignored. */
function readTab(): string | null {
  try {
    return sessionStorage.getItem(TAB_KEY);
  } catch {
    return null;
  }
}

function Shell(props: { farm: MeFarm; user: Me["user"]; store: DexieStore; api: ApiClient;
                        canSwitchFarm: boolean; onSwitchFarm: () => void; onLogout: () => void }): ReactNode {
  const { online, syncing, stats } = useSync();
  const can = (code: string) => props.farm.permissions.includes(code);
  const tabs: { id: Tab; label: string; visible: boolean }[] = [
    { id: "tasks", label: "Tâches", visible: can("tasks.view") },
    { id: "campaigns", label: "Campagnes", visible: can("plans.view") },
    { id: "parcels", label: "Parcelles", visible: can("fields.view") },
    { id: "finances", label: "Finances",
      visible: can("finance.view") || can("finance.transaction.create") || can("finance.funding.create") },
    { id: "sync", label: "Synchronisation", visible: true },
  ];
  const visible = tabs.filter((t) => t.visible);
  const [tab, setTabState] = useState<Tab>(() => {
    const saved = readTab();
    return visible.find((t) => t.id === saved)?.id ?? visible[0]?.id ?? "sync";
  });

  const setTab = (next: Tab) => {
    if (!visible.some((t) => t.id === next)) return;
    setTabState(next);
    try {
      sessionStorage.setItem(TAB_KEY, next);
    } catch {
      // ignored: see readTab
    }
  };

  const role = props.farm.is_org_admin && !props.farm.role ? "Administrateur de l'organisation"
    : roleLabel(props.farm.role);
  return (
    <div className="min-h-screen">
      <AppHeader
        user={props.user}
        title={props.farm.name}
        subtitle={props.canSwitchFarm && (
          <button type="button" className="text-sm text-green-800 underline" onClick={props.onSwitchFarm}>
            Changer d'exploitation
          </button>
        )}
        status={<SyncBadge online={online} syncing={syncing} stats={stats} />}
        profileContext={[role, props.farm.name].filter(Boolean).join(" · ")}
        currentFarmId={props.farm.id}
        onNotificationAction={setTab}
        onLogout={props.onLogout}>
        <nav className="mx-auto flex max-w-4xl gap-1 overflow-x-auto px-4" aria-label="Sections">
          {visible.map((t) => (
            <button key={t.id} type="button" aria-current={t.id === tab ? "page" : undefined}
                    onClick={() => setTab(t.id)}
                    className={`inline-flex min-h-11 shrink-0 items-center border-b-2 px-3 text-sm font-medium sm:min-h-10
                                focus-visible:outline-2 focus-visible:outline-green-700 ${t.id === tab
                                  ? "border-green-700 text-green-800"
                                  : "border-transparent text-stone-600 hover:text-stone-900"}`}>
              {t.label}
            </button>
          ))}
        </nav>
      </AppHeader>
      <main className={`mx-auto flex flex-col gap-4 p-4 ${tab === "finances" || tab === "campaigns" ? "max-w-6xl" : "max-w-4xl"}`}>
        <div className="sm:hidden"><OfflineBanner online={online} /></div>
        {tab === "parcels" && <ParcelsPage canEdit={can("fields.edit")} />}
        {tab === "tasks" && <TasksPage canReport={can("tasks.report")} />}
        {tab === "campaigns" && <CampaignsPage api={props.api} farm={props.farm} />}
        {tab === "finances" && <FinancePage api={props.api} farm={props.farm} userId={props.user.id} />}
        {tab === "sync" && <SyncPage store={props.store} />}
      </main>
    </div>
  );
}

export function App({ api = new ApiClient() }: { api?: ApiClient }): ReactNode {
  const [me, setMe] = useState<Me | null>(() => {
    const cached = localStorage.getItem(ME_CACHE);
    return cached && api.hasSession ? (JSON.parse(cached) as Me) : null;
  });
  const [farmId, setFarmId] = useState<string | null>(() => localStorage.getItem(FARM_KEY));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [unsentAtLogout, setUnsentAtLogout] = useState(0);

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
    if (api.hasSession) void loadMe();
    void requestPersistentStorage();
  }, [api, loadMe]);

  const logout = useCallback(() => {
    void api.logout();
    localStorage.removeItem(ME_CACHE);
    setUnsentAtLogout(0);
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

  /** Sensitive: unsent entries stay on the device; say so before leaving (CLAUDE.md §7). */
  const requestLogout = useCallback(() => {
    void (store ? store.countUnsent() : Promise.resolve(0)).then((unsent) => {
      if (unsent) setUnsentAtLogout(unsent);
      else logout();
    });
  }, [store, logout]);

  if (!me) {
    return loading ? <Loading /> : <LoginPage api={api} onLoggedIn={() => void loadMe()} />;
  }
  return (
    <NotificationsProvider key={me.user.id} userId={me.user.id}>
      {!farm || !engine || !store ? (
        <>
          {error && <div className="mx-auto max-w-2xl p-4"><ErrorMessage>{error}</ErrorMessage></div>}
          <FarmPicker me={me} api={api} onPick={pick} onLogout={requestLogout}
                      onFarmCreated={() => void loadMe()} />
        </>
      ) : (
        <SyncProvider key={farm.id} engine={engine} store={store} farmId={farm.id} onAuthRequired={logout}>
          <Shell farm={farm} user={me.user} store={store} api={api} onLogout={requestLogout}
                 canSwitchFarm={me.farms.length > 1} onSwitchFarm={() => setFarmId(null)} />
        </SyncProvider>
      )}
      <ConfirmDialog open={unsentAtLogout > 0} title="Se déconnecter ?" confirmLabel="Se déconnecter"
                     onCancel={() => setUnsentAtLogout(0)} onConfirm={logout}>
        Saisies pas encore envoyées au serveur : <strong>{unsentAtLogout}</strong>. Elles restent sur cet appareil
        et seront envoyées à votre prochaine connexion avec ce même compte.
      </ConfirmDialog>
    </NotificationsProvider>
  );
}
