import { roleLabel } from "@fms/shared";
import type { ReactNode } from "react";

import type { Me, MeFarm } from "../../api/types";
import { Button, EmptyState } from "../../ui/components";

export function FarmPicker(props: { me: Me; onPick: (farm: MeFarm) => void; onLogout: () => void }): ReactNode {
  const { farms, organizations, user } = props.me;
  const orgName = (id: string) => organizations.find((o) => o.id === id)?.name;
  const showOrg = new Set(farms.map((f) => f.organization_id)).size > 1;
  return (
    <main className="mx-auto mt-10 max-w-md p-4">
      <p className="text-sm text-stone-600">Bonjour {user.full_name}</p>
      <h1 className="mb-4 text-xl font-semibold">Choisir une exploitation</h1>
      {farms.length === 0 ? (
        <EmptyState>Aucune exploitation accessible. Demandez une invitation à votre administrateur.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-2">
          {farms.map((farm) => (
            <li key={farm.id}>
              <button type="button" onClick={() => props.onPick(farm)}
                      className="flex min-h-14 w-full flex-col items-start rounded-lg border border-stone-200
                                 bg-white px-4 py-3 text-left shadow-sm hover:border-green-700 hover:bg-green-50
                                 focus-visible:outline-2 focus-visible:outline-green-700">
                <span className="font-medium">{farm.name}</span>
                <span className="text-xs text-stone-500">
                  {[showOrg && orgName(farm.organization_id), farm.is_org_admin && !farm.role
                    ? "Administrateur de l'organisation" : roleLabel(farm.role)].filter(Boolean).join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Button variant="ghost" className="mt-6" onClick={props.onLogout}>Déconnexion</Button>
    </main>
  );
}
