import { describeError, describeOperation, formatAge, formatDateTime, operationDetails } from "@fms/shared";
import type { LocalOperation } from "@fms/sync-core";
import { type ReactNode, useEffect, useState } from "react";

import type { DexieStore } from "../../storage/dexieStore";
import { useSync } from "../../sync/SyncContext";
import { Button, Card, ConfirmDialog, EmptyState, LocalStatus, SectionHeader } from "../../ui/components";

const PROBLEM = new Set(["failed", "conflict"]);

/** Pending, failed and conflicting operations, with explicit user actions (FR-114). */
export function SyncPage({ store }: { store: DexieStore }): ReactNode {
  const { engine, farmId, revision, refresh, syncNow, syncing, lastReport, lastSyncAt, online } = useSync();
  const [ops, setOps] = useState<LocalOperation[]>([]);
  const [toAbandon, setToAbandon] = useState<LocalOperation | null>(null);

  useEffect(() => {
    void store.listOperations(farmId).then((list) =>
      // Problems first: they need the user; then oldest first (sending order).
      setOps(list.sort((a, b) => Number(PROBLEM.has(b.status)) - Number(PROBLEM.has(a.status))
        || a.createdAt.localeCompare(b.createdAt))));
  }, [store, farmId, revision]);

  async function retry(op: LocalOperation) {
    await engine.retry(op.opId, farmId);
    refresh();
    await syncNow();
  }

  async function abandon(op: LocalOperation) {
    await engine.abandon(op.opId, farmId);
    setToAbandon(null);
    refresh();
  }

  const problems = ops.filter((op) => PROBLEM.has(op.status)).length;
  const details = toAbandon ? operationDetails(toAbandon) : [];

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader title="Synchronisation">
        <Button onClick={() => void syncNow()} disabled={syncing}>
          {syncing ? "Synchronisation…" : "Synchroniser maintenant"}
        </Button>
      </SectionHeader>
      <Card className="p-3 text-sm text-stone-700">
        <p>
          Dernière synchronisation réussie :{" "}
          <span title={lastSyncAt ? formatDateTime(lastSyncAt) : undefined}>
            {lastSyncAt ? formatAge(lastSyncAt) : "pas encore pendant cette session"}
          </span>
        </p>
        {(lastReport?.offline || !online) && (
          <p className="text-stone-600">Serveur injoignable : nouvel essai automatique au retour du réseau.</p>
        )}
        {problems > 0 && (
          <p className="mt-1 font-medium text-red-800">
            {problems === 1 ? "1 saisie demande" : `${problems} saisies demandent`} votre attention. Les autres
            continuent d'être envoyées.
          </p>
        )}
      </Card>
      {ops.length === 0 ? <EmptyState>Toutes les données sont synchronisées.</EmptyState> : (
        <Card>
          <ul className="divide-y divide-stone-200">
            {ops.map((op) => (
              <li key={op.opId} className="flex flex-col gap-1 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{describeOperation(op)}</span>
                  <LocalStatus status={op.status} />
                </div>
                <span className="text-stone-500">Saisie le {formatDateTime(op.createdAt)}</span>
                {op.lastError && <span className="text-red-700">{describeError(op.lastError)}</span>}
                {PROBLEM.has(op.status) && (
                  <div className="mt-1 flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => void retry(op)}>Réessayer</Button>
                    <Button variant="danger" onClick={() => setToAbandon(op)}>Abandonner</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <ConfirmDialog open={toAbandon !== null} title="Abandonner cette saisie ?"
                     confirmLabel="Abandonner définitivement" onCancel={() => setToAbandon(null)}
                     onConfirm={() => toAbandon && void abandon(toAbandon)}>
        <p>
          <strong>{toAbandon && describeOperation(toAbandon)}</strong> ne sera jamais envoyée au serveur.
          Notez son contenu si vous devez la ressaisir :
        </p>
        {details.length > 0 && (
          <ul className="mt-2 list-inside list-disc rounded-md bg-stone-100 p-2">
            {details.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
        <details className="mt-2 text-xs text-stone-500">
          <summary className="cursor-pointer">Détails techniques</summary>
          <pre className="mt-1 max-h-32 overflow-auto rounded bg-stone-100 p-2">
            {JSON.stringify(toAbandon?.payload ?? {}, null, 1)}
          </pre>
        </details>
      </ConfirmDialog>
    </section>
  );
}
