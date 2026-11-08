import { formatDateRange, groupTasks, LOCAL_STATE_LABELS, pendingReports, TASK_STATUS_LABELS,
         todayIso } from "@fms/shared";
import { type ReactNode, useState } from "react";

import type { Task } from "../../api/types";
import { type LocalMeta, useLocalEntities, useSync } from "../../sync/SyncContext";
import { useNotifications } from "../../notifications/NotificationsContext";
import { Button, Card, ConfirmDialog, EmptyState, Loading, LocalStatus, useBusy } from "../../ui/components";

type Row = Task & LocalMeta;

const STATUS_STYLES: Record<Task["status"], string> = {
  todo: "bg-stone-100 text-stone-700",
  in_progress: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  cancelled: "bg-stone-100 text-stone-500",
  to_verify: "bg-amber-100 text-amber-900",
};

function TaskItem(props: { task: Row; late: boolean; canReport: boolean; reportState: string | undefined;
                           busy: boolean; onStart: () => void; onFinish: () => void }): ReactNode {
  const { task } = props;
  const open = task.status === "todo" || task.status === "in_progress";
  return (
    <li className={`flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between
                    ${props.late ? "border-l-4 border-l-red-600" : ""}`}>
      <div className="flex min-w-0 flex-col gap-1">
        <p className="font-medium">{task.title}</p>
        <p className="flex flex-wrap items-center gap-2 text-sm text-stone-600">
          <span>{formatDateRange(task.planned_start_date, task.planned_end_date)}</span>
          <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLES[task.status]}`}>
            {TASK_STATUS_LABELS[task.status]}
          </span>
          {props.late && <span className="text-xs font-semibold text-red-700">En retard</span>}
        </p>
        <LocalStatus status={task._local} />
        {props.reportState && (
          <p className="text-sm text-amber-900">Compte rendu : {props.reportState.toLowerCase()}</p>
        )}
      </div>
      {props.canReport && open && !props.reportState && (
        <div className="flex gap-2">
          {task.status === "todo" && (
            <Button variant="secondary" disabled={props.busy} onClick={props.onStart}>Démarrer</Button>
          )}
          <Button disabled={props.busy} onClick={props.onFinish}>Terminer</Button>
        </div>
      )}
    </li>
  );
}

export function TasksPage({ canReport }: { canReport: boolean }): ReactNode {
  const { record, farmId } = useSync();
  const { rows, loading } = useLocalEntities<Task>("tasks.task");
  const reports = useLocalEntities<{ task: string }>("tasks.task_report");
  const [busy, guard] = useBusy();
  const [busyTask, setBusyTask] = useState<string | null>(null);
  const [finishing, setFinishing] = useState<Row | null>(null);
  const [notes, setNotes] = useState("");
  const [showFinished, setShowFinished] = useState(false);
  const { notify } = useNotifications();
  const today = todayIso();
  const groups = groupTasks(rows, today);
  const reported = pendingReports(reports.rows);

  const run = (task: Row, action: () => Promise<unknown>) => guard(async () => {
    setBusyTask(task.id);
    try {
      await action();
    } finally {
      setBusyTask(null);
    }
  });

  const changeStatus = (task: Row, to: Task["status"]) => run(task, () =>
    // Offline command; the server detects stale transitions (OFFLINE_SYNC.md §6.2).
    record({
      opType: "command",
      command: "task.change_status",
      entityType: "tasks.task",
      entityId: task.id,
      payload: { from: task.status, to },
    }));

  const reportDone = (task: Row) => run(task, async () => {
    // Append-only field report; it also completes the task on the server.
    await record({
      opType: "create",
      entityType: "tasks.task_report",
      entityId: crypto.randomUUID(),
      payload: { task: task.id, actual_start: new Date().toISOString(), completion: "complete",
                 notes: notes.trim() },
    });
    setFinishing(null);
    setNotes("");
    notify({ type: "success", farmId,
             text: `« ${task.title} » terminée. Le compte rendu sera envoyé dès que possible.` });
  });

  const section = (title: string, list: Row[], tone: string, late = false) => list.length > 0 && (
    <div className="flex flex-col gap-2">
      <h3 className={`text-sm font-semibold uppercase tracking-wide ${tone}`}>{title} ({list.length})</h3>
      <Card>
        <ul className="divide-y divide-stone-200">
          {list.map((task) => {
            const report = reported.get(task.id);
            return (
              <TaskItem key={task._id} task={task} late={late} canReport={canReport}
                        reportState={report && LOCAL_STATE_LABELS[report]}
                        busy={busy && busyTask === task.id} onStart={() => void changeStatus(task, "in_progress")}
                        onFinish={() => setFinishing(task)} />
            );
          })}
        </ul>
      </Card>
    </div>
  );

  const openCount = groups.late.length + groups.today.length + groups.upcoming.length;
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Tâches</h2>
      {loading ? <Loading /> : openCount === 0 && groups.finished.length === 0 ? (
        <EmptyState hint="Les tâches sont générées à partir des plans de production.">
          Aucune tâche planifiée.
        </EmptyState>
      ) : (
        <>
          {openCount === 0 && <EmptyState>Aucune tâche à réaliser pour le moment.</EmptyState>}
          {section("En retard", groups.late, "text-red-700", true)}
          {section("En cours et du jour", groups.today, "text-green-800")}
          {section("À venir", groups.upcoming, "text-stone-600")}
          {groups.finished.length > 0 && (
            <div>
              <Button variant="ghost" aria-expanded={showFinished} onClick={() => setShowFinished(!showFinished)}>
                {showFinished ? "Masquer" : "Afficher"} les tâches terminées ({groups.finished.length})
              </Button>
              {showFinished && section("Terminées", groups.finished, "text-stone-600")}
            </div>
          )}
        </>
      )}
      <ConfirmDialog open={finishing !== null} title="Terminer la tâche ?" confirmLabel="Terminer"
                     variant="primary" onCancel={() => { setFinishing(null); setNotes(""); }}
                     onConfirm={() => finishing && void reportDone(finishing)}>
        <p className="mb-3">
          <strong>{finishing?.title}</strong> sera marquée comme réalisée. Le compte rendu ne pourra plus
          être retiré une fois envoyé.
        </p>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Observations ou écart au plan (facultatif)</span>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
                    className="rounded-md border border-stone-300 p-2" />
        </label>
      </ConfirmDialog>
    </section>
  );
}
