import type { NotificationTarget as NotificationTab } from "@fms/shared";
import type { ReactNode } from "react";

import type { Me } from "../api/types";
import { NotificationsMenu } from "../features/notifications/NotificationsMenu";
import { ProfileMenu } from "../features/profile/ProfileMenu";

/**
 * Header shown on every screen once signed in: notifications and profile menu are
 * always reachable (also on the farm picker).
 */
export function AppHeader(props: {
  user: Me["user"];
  title: ReactNode;
  subtitle?: ReactNode;
  status?: ReactNode;
  profileContext?: string;
  currentFarmId?: string | null;
  onNotificationAction?: (tab: NotificationTab) => void;
  onLogout: () => void;
  children?: ReactNode;
}): ReactNode {
  return (
    <header className="sticky top-0 z-20 border-b border-stone-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-2 px-4 py-2.5">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold">{props.title}</h1>
          {props.subtitle}
        </div>
        <div className="flex items-center gap-2">
          {props.status}
          <NotificationsMenu currentFarmId={props.currentFarmId ?? null} onAction={props.onNotificationAction} />
          <ProfileMenu user={props.user} context={props.profileContext} onLogout={props.onLogout} />
        </div>
      </div>
      {props.children}
    </header>
  );
}
