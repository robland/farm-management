/** Reusable presentation components (no business logic). */

import type { OpStatus } from "@fms/sync-core";
import { LOCAL_STATE_LABELS } from "@fms/shared";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-700";

export function Button(
  props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" },
): ReactNode {
  const { variant = "primary", className = "", ...rest } = props;
  const styles = {
    primary: "bg-green-700 text-white hover:bg-green-800",
    secondary: "bg-white text-stone-800 border border-stone-300 hover:bg-stone-100",
    danger: "bg-red-700 text-white hover:bg-red-800",
    ghost: "text-green-800 hover:bg-green-50",
  }[variant];
  // min-h-11: 44 px touch target on phones and tablets (NFR-006).
  return (
    <button
      type="button"
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm
                  font-medium disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS} ${styles} ${className}`}
      {...rest}
    />
  );
}

const INPUT = `min-h-11 w-full rounded-md border bg-white px-3 py-2 ${FOCUS}`;

export function Field(
  props: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string | undefined;
                                                  hint?: string | undefined },
): ReactNode {
  const { label, error, hint, ...rest } = props;
  const id = useId();
  const describedBy = [error && `${id}-error`, hint && `${id}-hint`].filter(Boolean).join(" ");
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={`${INPUT} ${error ? "border-red-600" : "border-stone-300"}`}
        {...rest}
      />
      {hint && !error && <p id={`${id}-hint`} className="text-xs text-stone-500">{hint}</p>}
      {error && <p id={`${id}-error`} className="text-sm text-red-700">{error}</p>}
    </div>
  );
}

/** Password input with a show/hide toggle (typing on a phone in the field). */
export function PasswordField(
  props: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: string },
): ReactNode {
  const { label, ...rest } = props;
  const id = useId();
  const [visible, setVisible] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <div className="flex gap-2">
        <input id={id} type={visible ? "text" : "password"} className={`${INPUT} border-stone-300`} {...rest} />
        <Button variant="secondary" aria-pressed={visible} aria-controls={id}
                onClick={() => setVisible(!visible)}>
          {visible ? "Masquer" : "Afficher"}
        </Button>
      </div>
    </div>
  );
}

export function Select(
  props: SelectHTMLAttributes<HTMLSelectElement> & {
    label: string;
    error?: string | undefined;
    options: { value: string; label: string }[];
    placeholder?: string;
  },
): ReactNode {
  const { label, error, options, placeholder = "Choisir…", ...rest } = props;
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <select id={id} aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${id}-error` : undefined}
              className={`${INPUT} ${error ? "border-red-600" : "border-stone-300"}`} {...rest}>
        <option value="">{placeholder}</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {error && <p id={`${id}-error`} className="text-sm text-red-700">{error}</p>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }): ReactNode {
  return <div className={`rounded-lg border border-stone-200 bg-white shadow-sm ${className}`}>{children}</div>;
}

/** Section title with an optional count and actions on the right. */
export function SectionHeader(props: { title: string; count?: number; children?: ReactNode }): ReactNode {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-lg font-semibold">
        {props.title}
        {props.count !== undefined && (
          <span className="ml-2 rounded-full bg-stone-200 px-2 py-0.5 text-xs font-medium text-stone-700">
            {props.count}
          </span>
        )}
      </h2>
      {props.children}
    </div>
  );
}

export function EmptyState(props: { children: ReactNode; hint?: string | undefined; action?: ReactNode })
  : ReactNode {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-stone-300 p-6
                    text-center text-stone-500">
      <p>{props.children}</p>
      {props.hint && <p className="text-sm">{props.hint}</p>}
      {props.action}
    </div>
  );
}

export function Loading(): ReactNode {
  return <p role="status" className="p-4 text-stone-500">Chargement…</p>;
}

export function ErrorMessage({ children }: { children: ReactNode }): ReactNode {
  return <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">{children}</p>;
}

/** Transient confirmation ("saved on this device"), announced to screen readers. */
export function Notice({ message, onClose }: { message: string | null; onClose: () => void }): ReactNode {
  return (
    <div aria-live="polite" className="empty:hidden">
      {message && (
        <p className="flex items-start justify-between gap-2 rounded-md border border-green-200 bg-green-50 p-3
                      text-sm text-green-900">
          <span>{message}</span>
          <button type="button" className={`rounded px-1 text-green-900 ${FOCUS}`} aria-label="Fermer"
                  onClick={onClose}>×</button>
        </p>
      )}
    </div>
  );
}

/** Message shown for a few seconds after a successful local save. */
export function useNotice(durationMs = 5000): [string | null, (message: string | null) => void] {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const show = useCallback((next: string | null) => {
    if (timer.current) clearTimeout(timer.current);
    setMessage(next);
    if (next) timer.current = setTimeout(() => setMessage(null), durationMs);
  }, [durationMs]);
  return [message, show];
}

/**
 * Runs one save at a time. The ref (not the state) guards: two clicks in the same tick
 * both see `busy === false`, and each would enqueue its own operation with a new UUID.
 */
export function useBusy(): [boolean, <T>(fn: () => Promise<T>) => Promise<T | undefined>] {
  const running = useRef(false);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    if (running.current) return undefined;
    running.current = true;
    setBusy(true);
    try {
      return await fn();
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, []);
  return [busy, run];
}

/** Per-item synchronization indicator (CLAUDE.md §7). */
export function LocalStatus({ status }: { status: OpStatus | null }): ReactNode {
  if (!status) return null;
  const color = status === "failed" || status === "conflict" ? "bg-red-100 text-red-800"
    : "bg-amber-100 text-amber-900";
  return <span className={`inline-block rounded px-2 py-0.5 text-xs ${color}`}>{LOCAL_STATE_LABELS[status]}</span>;
}

/** Global synchronization badge. */
export function SyncBadge(props: {
  online: boolean;
  syncing: boolean;
  stats: Record<OpStatus, number>;
}): ReactNode {
  const waiting = props.stats.pending + props.stats.syncing;
  const problems = props.stats.failed + props.stats.conflict;
  let text = props.online ? "En ligne" : "Hors ligne";
  if (props.syncing) text = "Synchronisation…";
  else if (waiting) text += ` · ${waiting} en attente`;
  if (problems) text += ` · ${problems} à traiter`;
  const color = problems ? "bg-red-700" : props.online ? "bg-green-700" : "bg-stone-600";
  return (
    <span role="status" className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs text-white ${color}`}>
      <span aria-hidden="true" className={`size-2 rounded-full bg-white ${props.syncing ? "animate-pulse" : ""}`} />
      {text}
    </span>
  );
}

/** Reassures the user that working offline is expected and safe (FR-110). */
export function OfflineBanner({ online }: { online: boolean }): ReactNode {
  if (online) return null;
  return (
    <p className="rounded-md border border-stone-300 bg-stone-100 p-3 text-sm text-stone-700">
      Vous êtes hors ligne. Vos saisies sont enregistrées sur cet appareil et seront envoyées
      automatiquement au retour du réseau.
    </p>
  );
}

export function ConfirmDialog(props: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  variant?: "primary" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}): ReactNode {
  const { open, onCancel } = props;
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    // Focus the safe choice first; Escape cancels.
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onCancel]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/40 p-4 sm:items-center"
         onClick={(event) => event.target === event.currentTarget && onCancel()}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId}
           className="w-full max-w-md rounded-lg bg-white p-4 shadow-lg">
        <h2 id={titleId} className="mb-2 font-semibold">{props.title}</h2>
        <div className="mb-4 text-sm">{props.children}</div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button ref={cancelRef} type="button" onClick={onCancel}
                  className={`min-h-11 rounded-md border border-stone-300 bg-white px-4 py-2 text-sm font-medium
                              hover:bg-stone-100 ${FOCUS}`}>
            Annuler
          </button>
          <Button variant={props.variant ?? "danger"} onClick={props.onConfirm}>{props.confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}
