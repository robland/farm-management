import { initials } from "@fms/shared";
import type { ReactNode } from "react";

import type { Me } from "../../api/types";
import { usePopover } from "../../ui/components";
import { PowerIcon } from "../../ui/icons";

/** Round avatar button; its menu holds the account details and the logout. */
export function ProfileMenu(props: { user: Me["user"]; context?: string; onLogout: () => void }): ReactNode {
  const { open, setOpen, rootRef, buttonRef } = usePopover();
  const contact = props.user.email ?? props.user.phone;
  return (
    <div ref={rootRef} className="relative">
      <button ref={buttonRef} type="button" aria-label={`Profil : ${props.user.full_name}`} aria-haspopup="menu"
              aria-expanded={open} onClick={() => setOpen(!open)}
              className="flex size-11 items-center justify-center rounded-full bg-green-800 text-sm font-semibold text-white
                         hover:bg-green-900 focus-visible:outline-2 focus-visible:outline-offset-2
                         focus-visible:outline-green-700 sm:size-9">
        {initials(props.user.full_name)}
      </button>
      {open && (
        <div role="menu" aria-label="Profil"
             className="absolute right-0 top-full z-30 mt-2 w-64 rounded-lg border border-stone-200 bg-white p-2 shadow-xl">
          <div className="mb-1.5 border-b border-stone-200 px-3 pt-2 pb-2.5">
            <p className="text-sm font-semibold">{props.user.full_name}</p>
            {contact && <p className="truncate text-sm text-stone-600">{contact}</p>}
            {props.context && <p className="mt-0.5 text-xs text-stone-600">{props.context}</p>}
          </div>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); props.onLogout(); }}
                  className="flex min-h-11 w-full items-center gap-2.5 rounded-md px-3 text-sm text-red-700
                             hover:bg-red-50 sm:min-h-9">
            <PowerIcon />
            Déconnexion
          </button>
        </div>
      )}
    </div>
  );
}
