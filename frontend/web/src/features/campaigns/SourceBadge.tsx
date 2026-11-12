import { label, SOURCE_KIND_LABELS } from "@fms/shared";
import type { ReactNode } from "react";

const STYLES: Record<string, string> = {
  document: "bg-sky-100 text-sky-900",
  calculation: "bg-green-100 text-green-800",
  ai_suggestion: "bg-violet-100 text-violet-800",
  user_input: "bg-stone-100 text-stone-700",
};

/** Where a value comes from (CLAUDE.md §10): never shown as documentary when it is not. */
export function SourceBadge({ kind, note }: { kind: string; note?: string }): ReactNode {
  return (
    <span title={note || undefined}
          className={`inline-flex w-fit rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${STYLES[kind] ?? STYLES.user_input}`}>
      {label(SOURCE_KIND_LABELS, kind)}
    </span>
  );
}
