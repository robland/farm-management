/**
 * In-app notifications shared by the web and mobile clients: synchronization problems,
 * inconsistencies to check, successes and new information. Pure functions only; each
 * client keeps the list in its own local storage.
 */

import { describeError, describeOperation, type LocalState, type OperationLike } from "./labels";

export type NotificationType = "sync" | "issue" | "success" | "info";
/** Where a notification's action leads: a web tab, or the matching mobile screen. */
export type NotificationTarget = "tasks" | "campaigns" | "parcels" | "finances" | "sync";

/** Targets renamed since earlier versions, still found in stored notifications. */
const LEGACY_TARGETS: Record<string, NotificationTarget> = { expenses: "finances" };

export interface AppNotification {
  /** Stable id: the same event notified twice (e.g. at each sync) is kept once. */
  id: string;
  type: NotificationType;
  text: string;
  createdAt: string;
  read: boolean;
  farmId: string | null;
  action?: { label: string; tab: NotificationTarget };
}

export type NotificationInput = Omit<AppNotification, "createdAt" | "read" | "id"> & { id?: string };

export const MAX_NOTIFICATIONS = 50;

export const NOTIFICATION_TYPE_LABELS: Record<NotificationType, string> = {
  sync: "Problème de synchronisation",
  issue: "Incohérence à vérifier",
  success: "Succès",
  info: "Nouvelle information",
};

export const NOTIFICATION_FILTERS: { id: NotificationType | "all"; label: string }[] = [
  { id: "all", label: "Toutes" },
  { id: "sync", label: "Synchronisation" },
  { id: "issue", label: "Incohérences" },
  { id: "success", label: "Succès" },
  { id: "info", label: "Infos" },
];

/** Newest first; an id already present is not added again; the list is capped. */
export function addNotification(list: AppNotification[], input: NotificationInput, now: Date,
                                makeId: () => string): AppNotification[] {
  const id = input.id ?? makeId();
  if (list.some((n) => n.id === id)) return list;
  const created: AppNotification = { ...input, id, createdAt: now.toISOString(), read: false };
  return [created, ...list].slice(0, MAX_NOTIFICATIONS);
}

export function markAllRead(list: AppNotification[]): AppNotification[] {
  return list.some((n) => !n.read) ? list.map((n) => (n.read ? n : { ...n, read: true })) : list;
}

export function markRead(list: AppNotification[], id: string): AppNotification[] {
  return list.map((n) => (n.id === id && !n.read ? { ...n, read: true } : n));
}

export function unreadCount(list: AppNotification[]): number {
  return list.filter((n) => !n.read).length;
}

export function filterNotifications(list: AppNotification[], filter: NotificationType | "all")
  : AppNotification[] {
  return filter === "all" ? list : list.filter((n) => n.type === filter);
}

/** Validates stored notifications, dropping anything malformed (storage is not trusted). */
export function sanitizeNotifications(value: unknown): AppNotification[] {
  if (!Array.isArray(value)) return [];
  return value.filter((n): n is AppNotification =>
    typeof n === "object" && n !== null && typeof n.id === "string" && typeof n.text === "string"
    && typeof n.createdAt === "string" && n.type in NOTIFICATION_TYPE_LABELS).slice(0, MAX_NOTIFICATIONS)
    .map((n) => {
      const legacy = n.action ? LEGACY_TARGETS[n.action.tab] : undefined;
      return legacy && n.action ? { ...n, action: { ...n.action, tab: legacy } } : n;
    });
}

export function parseStoredNotifications(raw: string | null): AppNotification[] {
  if (!raw) return [];
  try {
    return sanitizeNotifications(JSON.parse(raw));
  } catch {
    return [];
  }
}

// --- Derived from a synchronization round ------------------------------------------

export interface QueuedOperationLike extends OperationLike {
  opId: string;
  status: LocalState;
  attempts: number;
}

const plural = (n: number, one: string, many: string) => (n > 1 ? many : one);

export function syncNotifications(input: {
  farmId: string;
  report: { applied: number };
  operations: QueuedOperationLike[];
  newTaskCount: number;
}): NotificationInput[] {
  const { farmId, report } = input;
  const out: NotificationInput[] = [];
  if (report.applied > 0) {
    out.push({ type: "success", farmId,
               text: `${report.applied} ${plural(report.applied, "saisie envoyée", "saisies envoyées")} au serveur.` });
  }
  for (const op of input.operations) {
    if (op.status !== "failed" && op.status !== "conflict") continue;
    const reason = describeError(op.lastError);
    // One notification per refusal: a retried operation that fails again is notified again.
    const id = `op:${op.opId}:${op.status}:${op.attempts}`;
    out.push(op.status === "failed"
      ? { id, type: "sync", farmId, text: `${describeOperation(op)} refusée par le serveur.${reason ? ` ${reason}` : ""}`,
          action: { label: "Ouvrir la synchronisation", tab: "sync" } }
      : { id, type: "issue", farmId,
          text: `${describeOperation(op)} : conflit avec une modification faite ailleurs, à vérifier.${
            reason ? ` ${reason}` : ""}`,
          action: { label: "Ouvrir la synchronisation", tab: "sync" } });
  }
  if (input.newTaskCount > 0) {
    out.push({ type: "info", farmId, action: { label: "Voir les tâches", tab: "tasks" },
               text: `${input.newTaskCount} ${plural(input.newTaskCount, "nouvelle tâche planifiée",
                 "nouvelles tâches planifiées")}.` });
  }
  return out;
}

/** Notification for a local failure of the sync loop itself (e.g. local database). */
export function localSyncErrorNotification(farmId: string, error: unknown): NotificationInput {
  const message = error instanceof Error ? error.message : String(error);
  return { id: `local-error:${message}`, type: "sync", farmId,
           text: `La synchronisation a échoué sur cet appareil (${message}). Nouvel essai automatique.`,
           action: { label: "Ouvrir la synchronisation", tab: "sync" } };
}
