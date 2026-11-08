/**
 * Notification centre of the signed-in user. Kept in localStorage per user: it is a
 * convenience history (the sync queue stays the source of truth), so storage failures
 * are ignored rather than blocking the app.
 */

import {
  addNotification,
  type AppNotification,
  markAllRead,
  markRead,
  type NotificationInput,
  parseStoredNotifications,
  unreadCount,
} from "@fms/shared";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

export interface NotificationsState {
  notifications: AppNotification[];
  unread: number;
  notify: (input: NotificationInput) => void;
  markAllRead: () => void;
  markRead: (id: string) => void;
}

const NotificationsContext = createContext<NotificationsState | null>(null);

const storageKey = (userId: string) => `fms.notifications.${userId}`;

function load(userId: string): AppNotification[] {
  try {
    return parseStoredNotifications(localStorage.getItem(storageKey(userId)));
  } catch {
    return [];
  }
}

export function NotificationsProvider(props: { userId: string; children: ReactNode }): ReactNode {
  const { userId } = props;
  const [notifications, setNotifications] = useState<AppNotification[]>(() => load(userId));

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(userId), JSON.stringify(notifications));
    } catch {
      // ignored: see module comment
    }
  }, [userId, notifications]);

  const notify = useCallback((input: NotificationInput) => {
    setNotifications((list) => addNotification(list, input, new Date(), () => crypto.randomUUID()));
  }, []);
  const readAll = useCallback(() => setNotifications(markAllRead), []);
  const readOne = useCallback((id: string) => setNotifications((list) => markRead(list, id)), []);

  const value = useMemo<NotificationsState>(() => ({
    notifications, unread: unreadCount(notifications), notify, markAllRead: readAll, markRead: readOne,
  }), [notifications, notify, readAll, readOne]);
  return <NotificationsContext.Provider value={value}>{props.children}</NotificationsContext.Provider>;
}

export function useNotifications(): NotificationsState {
  const value = useContext(NotificationsContext);
  if (!value) throw new Error("useNotifications must be used inside <NotificationsProvider>");
  return value;
}
