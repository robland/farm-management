/** Presentation pieces of the finance screens (no business rules). */

import { formatMoney, transactionBadges, transactionDirection } from "@fms/shared";
import type { OpStatus } from "@fms/sync-core";
import type { ReactNode } from "react";
import { Text, View } from "react-native";

import { colors, LocalStatus, styles } from "../../ui/components";
import type { Tx } from "./data";

/** Amount with an explicit sign and colour: green in, red out, plain for internal moves. */
export function Amount({ tx, size = 15 }: { tx: Tx; size?: number }): ReactNode {
  const direction = transactionDirection(tx);
  const color = direction === "in" ? colors.primaryDark : direction === "out" ? colors.danger : colors.text;
  const sign = direction === "in" ? "+" : direction === "out" ? "−" : "";
  return (
    <Text style={{ fontWeight: "700", color, fontSize: size, fontVariant: ["tabular-nums"] }}>
      {sign}{formatMoney(tx.amount.replace(/^-/, ""), tx.currency)}
    </Text>
  );
}

const TONES = {
  ok: { backgroundColor: colors.primarySoft, color: colors.primaryDark },
  danger: { backgroundColor: colors.dangerSoft, color: colors.danger },
  pending: { backgroundColor: colors.warn, color: colors.warnText },
} as const;

export function TxBadges({ tx, local }: { tx: Tx; local: OpStatus | null }): ReactNode {
  if (local) return <LocalStatus status={local} />;
  return (
    <View style={styles.wrap}>
      {transactionBadges(tx).map((b) => (
        <Text key={b.label} style={[styles.badge, b.tone in TONES ? TONES[b.tone as keyof typeof TONES]
          : { backgroundColor: "#f5f5f4", color: colors.muted }]}>{b.label}</Text>
      ))}
    </View>
  );
}
