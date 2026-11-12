/** Generic controls shared by the tabs (no business rules). */

import type { Tone } from "@fms/shared";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import { Button } from "./components";

const TONES: Record<Tone, string> = {
  neutral: "bg-stone-100 text-stone-700",
  pending: "bg-amber-100 text-amber-900",
  ok: "bg-green-100 text-green-800",
  danger: "bg-red-100 text-red-800",
  muted: "bg-stone-100 text-stone-500",
  info: "bg-blue-100 text-blue-800",
};

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }): ReactNode {
  return <span className={`inline-block rounded px-2 py-0.5 text-xs whitespace-nowrap ${TONES[tone]}`}>{children}</span>;
}

/** Pill navigation between the sub-views of a tab. */
export function SubNav<T extends string>(props: { label: string; items: { id: T; label: string }[]; current: T;
                                                  onChange: (id: T) => void }): ReactNode {
  return (
    <nav aria-label={props.label} className="flex flex-wrap gap-1">
      {props.items.map((item) => (
        <button key={item.id} type="button" aria-current={item.id === props.current ? "page" : undefined}
                onClick={() => props.onChange(item.id)}
                className={`inline-flex min-h-11 items-center rounded-full px-3 text-sm whitespace-nowrap sm:min-h-8
                            focus-visible:outline-2 focus-visible:outline-green-700 ${item.id === props.current
                              ? "bg-stone-900 text-white" : "text-stone-700 hover:bg-stone-100"}`}>
          {item.label}
        </button>
      ))}
    </nav>
  );
}

/** Mutually exclusive choice shown as a segmented control (radio group). */
export function Segmented<T extends string>(props: { label: string; options: { id: T; label: string }[]; value: T;
                                                     onChange: (id: T) => void }): ReactNode {
  return (
    <div role="radiogroup" aria-label={props.label}
         className="inline-flex overflow-hidden rounded-md border border-stone-300 bg-white">
      {props.options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={o.id === props.value}
                onClick={() => props.onChange(o.id)}
                className={`min-h-11 border-r border-stone-300 px-3 text-sm last:border-r-0 sm:min-h-9
                            focus-visible:outline-2 focus-visible:outline-green-700 ${o.id === props.value
                              ? "bg-green-700 font-semibold text-white" : "text-stone-700 hover:bg-stone-50"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Dialog asking for a mandatory reason (reject, reverse): sensitive operations (CLAUDE.md §7). */
export function ReasonDialog(props: { open: boolean; title: string; description: ReactNode; confirmLabel: string;
                                      busy: boolean; error: string | null; onConfirm: (reason: string) => void;
                                      onCancel: () => void }): ReactNode {
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const titleId = useId();
  const fieldId = useId();
  const { open, onCancel } = props;
  useEffect(() => {
    if (!open) return;
    setReason("");
    setMissing(false);
    areaRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);
  if (!open) return null;
  const confirm = () => {
    if (!reason.trim()) {
      setMissing(true);
      return;
    }
    props.onConfirm(reason.trim());
  };
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/40 p-4 sm:items-center"
         onClick={(event) => event.target === event.currentTarget && onCancel()}>
      <div role="alertdialog" aria-modal="true" aria-labelledby={titleId}
           className="flex w-full max-w-md flex-col gap-3 rounded-lg bg-white p-4 shadow-lg">
        <h2 id={titleId} className="font-semibold">{props.title}</h2>
        <div className="text-sm text-stone-700">{props.description}</div>
        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className="text-sm font-medium">Motif (obligatoire)</label>
          <textarea ref={areaRef} id={fieldId} rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                    aria-invalid={missing || undefined}
                    className={`rounded-md border px-3 py-2 ${missing ? "border-red-600" : "border-stone-300"}`} />
          {missing && <p className="text-sm text-red-700">Indiquez le motif.</p>}
        </div>
        {props.error && <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-800">{props.error}</p>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onCancel}>Retour</Button>
          <Button variant="danger" disabled={props.busy} onClick={confirm}>
            {props.busy ? "Envoi…" : props.confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
