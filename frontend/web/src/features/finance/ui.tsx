/** Presentation pieces of the Finances tab (no business rules). */

import { formatDateTime, formatMoney } from "@fms/shared";
import type { ReactNode } from "react";

import { Button } from "../../ui/components";

export { Badge, ReasonDialog, Segmented, SubNav } from "../../ui/controls";

/** Amount with an explicit sign and colour: green in, red out, grey for internal moves. */
export function Money(props: { amount: string; currency: string; direction?: "in" | "out" | "move";
                               className?: string }): ReactNode {
  const { amount, currency, direction } = props;
  const color = direction === "in" ? "text-green-800" : direction === "out" ? "text-red-700" : "";
  const sign = direction === "in" ? "+" : direction === "out" ? "−" : "";
  return (
    <span className={`font-semibold tabular-nums whitespace-nowrap ${color} ${props.className ?? ""}`}>
      {sign}{formatMoney(amount.replace(/^-/, ""), currency)}
    </span>
  );
}

/** Signed amount (variance, result): "−12 500 XAF". */
export function SignedMoney({ amount, currency }: { amount: string; currency: string }): ReactNode {
  const negative = amount.startsWith("-");
  return <span className="tabular-nums">{negative ? "−" : ""}{formatMoney(amount.replace(/^-/, ""), currency)}</span>;
}

/** "Données du 9 nov. 2026 à 10:15" when the screen shows a cached answer. */
export function Freshness(props: { offline: boolean; error: string | null; fetchedAt: string | null;
                                   onRetry: () => void }): ReactNode {
  if (!props.error) return null;
  return (
    <p role="status" className="flex flex-wrap items-center gap-2 rounded-md bg-stone-100 p-2 text-sm text-stone-700">
      {props.offline ? "Hors ligne" : props.error}
      {props.fetchedAt ? ` · données du ${formatDateTime(props.fetchedAt)}` : " · aucune donnée enregistrée"}
      <Button variant="ghost" onClick={props.onRetry}>Réessayer</Button>
    </p>
  );
}

