/** Reusable presentation components (no business logic). */

import { LOCAL_STATE_LABELS } from "@fms/shared";
import type { OpStatus } from "@fms/sync-core";
import { type ReactNode, type Ref, useCallback, useRef, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput,
         type TextInputInstance, type TextInputProps, View } from "react-native";

export const colors = { primary: "#15803d", primaryDark: "#166534", primarySoft: "#dcfce7",
                        danger: "#b91c1c", dangerSoft: "#fee2e2", muted: "#57534e", border: "#d6d3d1",
                        background: "#fafaf9", warn: "#fef3c7", warnText: "#78350f", text: "#1c1917",
                        offline: "#57534e" };

/** Minimum touch target (Android guideline 48 dp), for use with gloves or in the sun. */
const TOUCH = 48;

export function Button(props: { title: string; onPress: () => void;
                                variant?: "primary" | "secondary" | "danger"; disabled?: boolean;
                                busy?: boolean; subtitle?: string; badge?: number }): ReactNode {
  const variant = props.variant ?? "primary";
  const disabled = props.disabled || props.busy;
  const textStyle = variant === "secondary" ? styles.secondaryText : styles.primaryText;
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ disabled: Boolean(disabled), busy: props.busy }}
               accessibilityLabel={props.badge ? `${props.title}, ${props.badge} à traiter` : undefined}
               disabled={disabled} onPress={props.onPress}
               style={({ pressed }) => [styles.button, styles[variant], pressed && styles.pressed,
                                        disabled && { opacity: 0.5 }]}>
      <View style={styles.buttonRow}>
        {props.busy ? <ActivityIndicator color={variant === "secondary" ? colors.text : "white"} /> : null}
        <Text style={textStyle}>{props.title}</Text>
        {props.badge ? <Text style={styles.countBadge}>{props.badge}</Text> : null}
      </View>
      {props.subtitle ? (
        <Text style={[textStyle, styles.subtitle]}>{props.subtitle}</Text>
      ) : null}
    </Pressable>
  );
}

export function Field(props: TextInputProps & { label: string; error?: string | null; hint?: string }): ReactNode {
  const { label, error, hint, ...rest } = props;
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput accessibilityLabel={label} accessibilityHint={error ?? hint}
                 placeholderTextColor="#a8a29e"
                 style={[styles.input, props.multiline && styles.multiline,
                         error ? { borderColor: colors.danger } : null]}
                 {...rest} />
      {hint && !error ? <Text style={styles.hint}>{hint}</Text> : null}
      {error ? <Text accessibilityLiveRegion="polite" style={styles.error}>{error}</Text> : null}
    </View>
  );
}

/** Password with a show/hide toggle: typing errors are frequent on a phone. */
export function PasswordField(props: Omit<TextInputProps, "secureTextEntry">
  & { label: string; ref?: Ref<TextInputInstance> }): ReactNode {
  const { label, ref, ...rest } = props;
  const [visible, setVisible] = useState(false);
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.inline}>
        <TextInput ref={ref} accessibilityLabel={label} secureTextEntry={!visible} autoCapitalize="none"
                   autoCorrect={false} style={[styles.input, { flex: 1 }]} {...rest} />
        <Pressable accessibilityRole="button" accessibilityState={{ selected: visible }}
                   accessibilityLabel={visible ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                   onPress={() => setVisible(!visible)} style={styles.toggle}>
          <Text style={styles.link}>{visible ? "Masquer" : "Afficher"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

export function Choice<T extends string>(props: { label: string; value: T | null;
  options: { value: T; label: string }[]; onChange: (value: T) => void; error?: string | null }): ReactNode {
  return (
    <View style={styles.field} accessibilityRole="radiogroup" accessibilityLabel={props.label}>
      <Text style={styles.label}>{props.label}</Text>
      <View style={styles.wrap}>
        {props.options.map((o) => {
          const selected = o.value === props.value;
          return (
            <Pressable key={o.value} accessibilityRole="radio" accessibilityState={{ selected }}
                       onPress={() => props.onChange(o.value)}
                       style={({ pressed }) => [styles.chip, selected && styles.chipSelected,
                                                pressed && styles.pressed]}>
              <Text style={selected ? styles.primaryText : styles.chipText}>{selected ? "✓ " : ""}{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      {props.error ? <Text accessibilityLiveRegion="polite" style={styles.error}>{props.error}</Text> : null}
    </View>
  );
}

export function LocalStatus({ status }: { status: OpStatus | null }): ReactNode {
  if (!status) return null;
  const bad = status === "failed" || status === "conflict";
  return (
    <Text style={[styles.badge, { backgroundColor: bad ? colors.dangerSoft : colors.warn,
                                  color: bad ? colors.danger : colors.warnText }]}>
      {LOCAL_STATE_LABELS[status]}
    </Text>
  );
}

/** Scrollable screen. Taps on buttons work while the keyboard is open; optional pull-to-refresh. */
export function Screen(props: { children: ReactNode; onRefresh?: () => void; refreshing?: boolean }): ReactNode {
  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}
                keyboardShouldPersistTaps="handled" automaticallyAdjustKeyboardInsets
                refreshControl={props.onRefresh ? (
                  <RefreshControl refreshing={Boolean(props.refreshing)} onRefresh={props.onRefresh}
                                  colors={[colors.primary]} />
                ) : undefined}>
      {props.children}
    </ScrollView>
  );
}

export function Empty(props: { children: string; hint?: string; action?: { title: string; onPress: () => void } })
  : ReactNode {
  return (
    <View style={styles.emptyBox}>
      <Text style={styles.empty}>{props.children}</Text>
      {props.hint ? <Text style={[styles.muted, { textAlign: "center" }]}>{props.hint}</Text> : null}
      {props.action ? <Button variant="secondary" title={props.action.title} onPress={props.action.onPress} /> : null}
    </View>
  );
}

/** Confirmation after a local save, announced by screen readers. */
export function Notice({ message, onClose }: { message: string | null; onClose: () => void }): ReactNode {
  if (!message) return null;
  return (
    <View accessibilityLiveRegion="polite" style={styles.notice}>
      <Text style={{ flex: 1, color: colors.primaryDark }}>{message}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Fermer" onPress={onClose} hitSlop={12}>
        <Text style={{ color: colors.primaryDark, fontSize: 18 }}>×</Text>
      </Pressable>
    </View>
  );
}

export function SectionTitle({ children, color }: { children: string; color?: string }): ReactNode {
  return <Text accessibilityRole="header" style={[styles.section, color ? { color } : null]}>{children}</Text>;
}

/**
 * Runs one save at a time. A ref guards (state updates are asynchronous): a double tap
 * would otherwise enqueue two operations with two UUIDs, e.g. two expenses.
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

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, gap: 12, paddingBottom: 32 },
  title: { fontSize: 22, fontWeight: "700", color: colors.text },
  section: { fontSize: 13, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5,
             color: colors.muted, marginTop: 8 },
  card: { backgroundColor: "white", borderColor: colors.border, borderWidth: 1, borderRadius: 10,
          padding: 12, gap: 8 },
  muted: { color: colors.muted },
  button: { borderRadius: 8, minHeight: TOUCH, paddingVertical: 12, paddingHorizontal: 14,
            alignItems: "center", justifyContent: "center" },
  buttonRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  primary: { backgroundColor: colors.primary },
  secondary: { backgroundColor: "white", borderWidth: 1, borderColor: colors.border },
  danger: { backgroundColor: colors.danger },
  pressed: { opacity: 0.75 },
  primaryText: { color: "white", fontWeight: "600", fontSize: 16 },
  secondaryText: { color: colors.text, fontWeight: "600", fontSize: 16 },
  subtitle: { fontWeight: "400", fontSize: 13, opacity: 0.9, marginTop: 2 },
  countBadge: { backgroundColor: colors.danger, color: "white", borderRadius: 10, minWidth: 20,
                paddingHorizontal: 6, textAlign: "center", fontSize: 12, fontWeight: "700", overflow: "hidden" },
  field: { gap: 4 },
  label: { fontWeight: "600", color: colors.text },
  hint: { color: colors.muted, fontSize: 12 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, minHeight: TOUCH,
           backgroundColor: "white", fontSize: 16, color: colors.text },
  multiline: { minHeight: 88, textAlignVertical: "top" },
  inline: { flexDirection: "row", alignItems: "center", gap: 8 },
  toggle: { minHeight: TOUCH, justifyContent: "center", paddingHorizontal: 8 },
  link: { color: colors.primaryDark, fontWeight: "600" },
  error: { color: colors.danger },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderColor: colors.border, borderRadius: 22, minHeight: 44, justifyContent: "center",
          paddingHorizontal: 14, backgroundColor: "white" },
  chipSelected: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.text, fontSize: 15 },
  badge: { alignSelf: "flex-start", borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2,
           fontSize: 12, overflow: "hidden" },
  emptyBox: { gap: 12, padding: 24, alignItems: "stretch" },
  empty: { textAlign: "center", color: colors.muted, fontSize: 16 },
  notice: { flexDirection: "row", gap: 8, alignItems: "flex-start", backgroundColor: colors.primarySoft,
            borderRadius: 8, padding: 12 },
});
