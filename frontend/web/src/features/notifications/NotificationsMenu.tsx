import { formatAge } from "@fms/shared";
import { type ReactNode, useState } from "react";

import { FILTERS, filterNotifications, type NotificationTab, type NotificationType,
         TYPE_LABELS } from "../../notifications/model";
import { useNotifications } from "../../notifications/NotificationsContext";
import { AlertIcon, BellIcon, CheckIcon, InfoIcon, SyncAlertIcon } from "../../ui/icons";
import { IconButton, usePopover } from "../../ui/components";

const TYPE_STYLES: Record<NotificationType, { icon: () => ReactNode; badge: string; text: string }> = {
  sync: { icon: SyncAlertIcon, badge: "bg-red-100 text-red-700", text: "text-red-700" },
  issue: { icon: AlertIcon, badge: "bg-orange-100 text-orange-700", text: "text-orange-700" },
  success: { icon: CheckIcon, badge: "bg-green-100 text-green-700", text: "text-green-800" },
  info: { icon: InfoIcon, badge: "bg-blue-100 text-blue-700", text: "text-blue-700" },
};

/**
 * Bell with the unread count and its panel. Actions (open a tab) are offered only for
 * the farm being displayed, and only where a navigation handler exists.
 */
export function NotificationsMenu(props: { currentFarmId?: string | null;
                                           onAction?: (tab: NotificationTab) => void }): ReactNode {
  const { notifications, unread, markAllRead, markRead } = useNotifications();
  const { open, setOpen, rootRef, buttonRef } = usePopover();
  const [filter, setFilter] = useState<NotificationType | "all">("all");
  const shown = filterNotifications(notifications, filter);

  return (
    <div ref={rootRef} className="relative">
      <IconButton ref={buttonRef} label="Notifications" badge={unread} aria-expanded={open}
                  aria-controls="notifications-panel" onClick={() => setOpen(!open)}>
        <BellIcon />
      </IconButton>
      {open && (
        <section id="notifications-panel" aria-label="Notifications"
                 className="absolute right-0 top-full z-30 mt-2 flex max-h-[min(36rem,80vh)] w-[min(24rem,calc(100vw-2rem))]
                            flex-col overflow-hidden rounded-lg border border-stone-200 bg-white shadow-xl">
          <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
            <h2 className="font-semibold">Notifications</h2>
            {unread > 0 && (
              <button type="button" onClick={markAllRead}
                      className="rounded px-1.5 py-1 text-sm font-medium text-green-800 hover:bg-green-50">
                Tout marquer comme lu
              </button>
            )}
          </div>
          <div role="group" aria-label="Filtrer les notifications"
               className="flex gap-1.5 overflow-x-auto border-b border-stone-200 px-4 pb-3">
            {FILTERS.map((f) => (
              <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}
                      className={`h-8 shrink-0 rounded-full border px-3 text-sm font-medium ${filter === f.id
                        ? "border-green-800 bg-green-800 text-white"
                        : "border-stone-300 bg-white text-stone-700 hover:bg-stone-100"}`}>
                {f.label}
              </button>
            ))}
          </div>
          {shown.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-stone-600">
              {notifications.length === 0 ? "Aucune notification pour le moment."
                : "Aucune notification dans cette catégorie."}
            </p>
          ) : (
            <ul className="overflow-y-auto">
              {shown.map((n) => {
                const style = TYPE_STYLES[n.type];
                const Icon = style.icon;
                const action = n.action && props.onAction && n.farmId === props.currentFarmId ? n.action : null;
                return (
                  <li key={n.id} className={`flex gap-3 border-b border-stone-100 px-4 py-3 ${n.read ? "" : "bg-green-50/40"}`}>
                    <span className={`flex size-8 shrink-0 items-center justify-center rounded-full ${style.badge}`}>
                      <Icon />
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <p className="flex justify-between gap-2 text-xs text-stone-600">
                        <span className={`font-semibold ${style.text}`}>{TYPE_LABELS[n.type]}</span>
                        <time dateTime={n.createdAt}>{formatAge(new Date(n.createdAt))}</time>
                      </p>
                      <p className="text-sm">{n.text}</p>
                      {action && (
                        <div>
                          <button type="button"
                                  onClick={() => {
                                    markRead(n.id);
                                    setOpen(false);
                                    props.onAction?.(action.tab);
                                  }}
                                  className="h-7 rounded-md border border-stone-300 px-2.5 text-sm font-medium text-green-800
                                             hover:bg-green-50">
                            {action.label}
                          </button>
                        </div>
                      )}
                    </div>
                    {!n.read && (
                      <span className="mt-1.5 size-2 shrink-0 rounded-full bg-green-700">
                        <span className="sr-only">Non lue</span>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
