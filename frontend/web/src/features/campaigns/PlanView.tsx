/** One production plan: its draft opens the editor, a validated version its results. */

import { label, PLAN_STATUS_LABELS, planRights, VERSION_ORIGIN_LABELS, VERSION_STATUS_LABELS } from "@fms/shared";
import { type ReactNode, useEffect, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { MeFarm, PlanVersion, ProductionPlan } from "../../api/types";
import { useSync } from "../../sync/SyncContext";
import { Badge } from "../../ui/controls";
import { Button, EmptyState } from "../../ui/components";
import { type Planning, shownVersion } from "./data";
import { PlanDetail } from "./PlanDetail";
import { PlanEditor } from "./PlanEditor";

export function PlanView(props: { api: ApiClient; farm: MeFarm; plan: ProductionPlan; planning: Planning;
                                  onBack: () => void }): ReactNode {
  const { syncNow } = useSync();
  const rights = planRights(props.farm.permissions);
  const synced = shownVersion(props.plan, props.planning.versions);
  // The server's answer to a write is fresher than the local store until the next sync.
  const [fresh, setFresh] = useState<PlanVersion | undefined>(undefined);
  const version = fresh && (!synced || fresh.id !== synced.id || fresh.version >= synced.version) ? fresh : synced;
  const campaign = props.planning.campaigns.find((c) => c.id === props.plan.campaign);

  useEffect(() => {
    if (fresh && synced && fresh.id === synced.id && synced.version > fresh.version) setFresh(undefined);
  }, [fresh, synced]);

  const onChange = (next: PlanVersion) => {
    setFresh(next);
    void syncNow();
  };

  return (
    <section className="flex flex-col gap-4" aria-label={`Plan ${props.plan.name}`}>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={props.onBack} aria-label="Retour à la campagne">← Campagne</Button>
        <div className="min-w-0">
          <p className="text-sm text-stone-500">{campaign?.name} · Variété {props.plan.variety_name}</p>
          <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
            {props.plan.name}
            {version && <span className="font-normal text-stone-500">· version {version.number}</span>}
            {version && (
              <Badge tone={version.status === "draft" ? "neutral" : version.status === "validated" ? "ok" : "muted"}>
                {version.status === "validated" ? label(PLAN_STATUS_LABELS, props.plan.status)
                  : label(VERSION_STATUS_LABELS, version.status)}
              </Badge>
            )}
            {version?.origin === "ai_draft" && version.status === "draft" && <Badge tone="info">{VERSION_ORIGIN_LABELS.ai_draft}</Badge>}
          </h2>
        </div>
      </div>
      {!version ? (
        <EmptyState>Aucune version de ce plan sur cet appareil. Synchronisez pour la télécharger.</EmptyState>
      ) : version.status === "draft" && rights.edit ? (
        <PlanEditor api={props.api} farm={props.farm} plan={props.plan} version={version} planning={props.planning}
                    onChange={onChange} />
      ) : (
        <PlanDetail api={props.api} farm={props.farm} plan={props.plan} version={version} planning={props.planning}
                    onChange={onChange} />
      )}
    </section>
  );
}
