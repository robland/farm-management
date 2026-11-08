import { formatDateRange, groupTasks, LOCAL_STATE_LABELS, pendingReports, TASK_STATUS_LABELS,
         todayIso } from "@fms/shared";
import type { OpStatus } from "@fms/sync-core";
import * as Crypto from "expo-crypto";
import { type ReactNode, useState } from "react";
import { Alert, Text, View } from "react-native";

import { useLocalEntities, useSession } from "../session/Session";
import { Button, colors, Empty, Field, LocalStatus, Screen, SectionTitle, styles,
         useBusy } from "../ui/components";

interface Task {
  id: string;
  title: string;
  status: "todo" | "in_progress" | "done" | "cancelled" | "to_verify";
  planned_start_date: string;
  planned_end_date: string;
}

type Row = Task & { _id: string; _local: OpStatus | null };

export default function Tasks(): ReactNode {
  const { record, can, syncNow, syncing, notify, farm } = useSession();
  const tasks = useLocalEntities<Task>("tasks.task");
  const reports = useLocalEntities<{ task: string }>("tasks.task_report");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, run] = useBusy();
  const groups = groupTasks(tasks, todayIso());
  const reported = pendingReports(reports);
  const canReport = can("tasks.report");

  const start = (task: Row) => void run(() => record({
    opType: "command", command: "task.change_status", entityType: "tasks.task", entityId: task.id,
    payload: { from: task.status, to: "in_progress" },
  }));

  const finish = (task: Row) => void run(async () => {
    // Field report (FR-063): kept even if the task changed meanwhile on the server.
    await record({
      opType: "create", entityType: "tasks.task_report", entityId: Crypto.randomUUID(),
      payload: { task: task.id, actual_start: new Date().toISOString(), completion: "complete",
                 notes: (notes[task.id] ?? "").trim() },
    });
    notify({ type: "success", farmId: farm?.id ?? null,
             text: `« ${task.title} » terminée. Le compte rendu sera envoyé dès que possible.` });
  });

  // A report cannot be withdrawn once sent: confirm first (CLAUDE.md §7).
  const confirmFinish = (task: Row) => Alert.alert("Terminer la tâche ?",
    `« ${task.title} » sera marquée comme réalisée.`, [
      { text: "Annuler", style: "cancel" },
      { text: "Terminer", onPress: () => finish(task) },
    ]);

  const card = (task: Row, late: boolean) => {
    const open = task.status === "todo" || task.status === "in_progress";
    const report = reported.get(task.id);
    return (
      <View key={task._id} style={[styles.card, late && { borderLeftWidth: 6, borderLeftColor: colors.danger }]}>
        <Text style={{ fontWeight: "600", fontSize: 16 }}>{task.title}</Text>
        <Text style={styles.muted}>
          {formatDateRange(task.planned_start_date, task.planned_end_date)} · {TASK_STATUS_LABELS[task.status]}
        </Text>
        {late ? <Text style={{ color: colors.danger, fontWeight: "700" }}>En retard</Text> : null}
        <LocalStatus status={task._local} />
        {report ? <Text style={{ color: colors.warnText }}>Compte rendu : {LOCAL_STATE_LABELS[report].toLowerCase()}</Text>
          : null}
        {canReport && open && !report ? (
          <>
            <Field label="Observations / écart au plan (facultatif)" value={notes[task.id] ?? ""} multiline
                   onChangeText={(text) => setNotes({ ...notes, [task.id]: text })} />
            <View style={{ flexDirection: "row", gap: 8 }}>
              {task.status === "todo" ? (
                <View style={{ flex: 1 }}>
                  <Button variant="secondary" title="Démarrer" disabled={busy} onPress={() => start(task)} />
                </View>
              ) : null}
              <View style={{ flex: 1 }}>
                <Button title="Terminer" disabled={busy} onPress={() => confirmFinish(task)} />
              </View>
            </View>
          </>
        ) : null}
      </View>
    );
  };

  const open = groups.late.length + groups.today.length + groups.upcoming.length;
  return (
    <Screen onRefresh={() => void syncNow()} refreshing={syncing}>
      {open === 0 ? (
        <Empty hint="Tirez vers le bas pour synchroniser. Les tâches viennent des plans de production.">
          Aucune tâche à réaliser.
        </Empty>
      ) : null}
      {groups.late.length ? <SectionTitle color={colors.danger}>{`En retard (${groups.late.length})`}</SectionTitle> : null}
      {groups.late.map((t) => card(t, true))}
      {groups.today.length ? <SectionTitle color={colors.primaryDark}>{`Du jour (${groups.today.length})`}</SectionTitle>
        : null}
      {groups.today.map((t) => card(t, false))}
      {groups.upcoming.length ? <SectionTitle>{`À venir (${groups.upcoming.length})`}</SectionTitle> : null}
      {groups.upcoming.map((t) => card(t, false))}
    </Screen>
  );
}
