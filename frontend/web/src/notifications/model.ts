/**
 * In-app notifications (no business logic): synchronization problems, inconsistencies
 * to check, successes and new information. Pure functions, so they are unit tested.
 */

export type NotificationType = "sync" | "issue" | "success" | "info";
export type NotificationTab = "tasks" | "parcels" | "expenses" | "sync";

export interface AppNotification {
  /** Stable id: the same event notified twice (e.g. at each sync) is kept once. */
  id: string;
  type: NotificationType;
  text: string;
  createdAt: string;
  read: boolean;
  farmId: string | null;
  action?: { label: string; tab: NotificationTab };
}

export type NotificationInput = Omit<AppNotification, "createdAt" | "read" | "id"> & { id?: string };

export const MAX_NOTIFICATIONS = 50;

export const TYPE_LABELS: Record<NotificationType, string> = {
  sync: "Problème de synchronisation",
  issue: "Incohérence à vérifier",
  success: "Succès",
  info: "Nouvelle information",
};

export const FILTERS: { id: NotificationType | "all"; label: string }[] = [
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

/** Parses stored notifications, dropping anything malformed (storage is not trusted). */
export function parseStored(raw: string | null): AppNotification[] {
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    return value.filter((n): n is AppNotification =>
      typeof n === "object" && n !== null && typeof n.id === "string" && typeof n.text === "string"
      && typeof n.createdAt === "string" && n.type in TYPE_LABELS).slice(0, MAX_NOTIFICATIONS);
  } catch {
    return [];
  }
}
