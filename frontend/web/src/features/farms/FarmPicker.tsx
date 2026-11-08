import { roleLabel } from "@fms/shared";
import { type ReactNode, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { Me, MeFarm } from "../../api/types";
import { AppHeader } from "../../app/AppHeader";
import { useNotifications } from "../../notifications/NotificationsContext";
import { Button, EmptyState } from "../../ui/components";
import { PlusIcon } from "../../ui/icons";
import { CreateFarmDialog } from "./CreateFarmDialog";

/** Organizations to list: those with a farm, plus those the user administers (to create one). */
export function organizationGroups(me: Me): { id: string; name: string; isAdmin: boolean; farms: MeFarm[] }[] {
  const ids = new Set([...me.farms.map((f) => f.organization_id),
                       ...me.organizations.filter((o) => o.is_org_admin).map((o) => o.id)]);
  return [...ids].map((id) => {
    const org = me.organizations.find((o) => o.id === id);
    return { id, name: org?.name ?? "Organisation", isAdmin: Boolean(org?.is_org_admin),
             farms: me.farms.filter((f) => f.organization_id === id) };
  });
}

export function FarmPicker(props: { me: Me; api: ApiClient; onPick: (farm: MeFarm) => void;
                                    onLogout: () => void; onFarmCreated: () => void }): ReactNode {
  const { me } = props;
  const { notify } = useNotifications();
  const [creatingIn, setCreatingIn] = useState<{ id: string; name: string } | null>(null);
  const groups = organizationGroups(me);

  return (
    <div className="min-h-screen">
      <AppHeader user={me.user} title="Gestion agricole" onLogout={props.onLogout} />
      <main className="mx-auto flex max-w-2xl flex-col gap-6 p-4 pt-6">
        <div>
          <p className="text-sm text-stone-600">Bonjour {me.user.full_name}</p>
          <h2 className="text-xl font-semibold">Choisir une exploitation</h2>
        </div>
        {groups.length === 0 ? (
          <EmptyState>Aucune exploitation accessible. Demandez une invitation à votre administrateur.</EmptyState>
        ) : groups.map((group) => (
          <section key={group.id} aria-labelledby={`org-${group.id}`} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 id={`org-${group.id}`} className="text-sm font-semibold tracking-wide text-stone-600 uppercase">
                {group.name}
              </h3>
              {group.isAdmin && (
                <Button variant="secondary" className="text-green-800"
                        onClick={() => setCreatingIn({ id: group.id, name: group.name })}>
                  <PlusIcon /> Créer une exploitation
                </Button>
              )}
            </div>
            {group.farms.length === 0 ? (
              <p className="text-sm text-stone-600">Aucune exploitation dans cette organisation pour le moment.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {group.farms.map((farm) => (
                  <li key={farm.id}>
                    <button type="button" onClick={() => props.onPick(farm)}
                            className="flex min-h-14 w-full flex-col items-start rounded-lg border border-stone-200
                                       bg-white px-4 py-2.5 text-left hover:border-green-700 hover:bg-green-50
                                       focus-visible:outline-2 focus-visible:outline-green-700">
                      <span className="font-medium">{farm.name}</span>
                      <span className="text-xs text-stone-600">
                        {farm.is_org_admin && !farm.role ? "Administrateur de l'organisation" : roleLabel(farm.role)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </main>
      {creatingIn && (
        <CreateFarmDialog api={props.api} organization={creatingIn} onCancel={() => setCreatingIn(null)}
                          onCreated={(name) => {
                            setCreatingIn(null);
                            notify({ type: "success", farmId: null, text: `Exploitation « ${name} » créée.` });
                            props.onFarmCreated();
                          }} />
      )}
    </div>
  );
}
