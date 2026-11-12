import Ionicons from "@expo/vector-icons/Ionicons";
import { filterNotifications, formatAge, NOTIFICATION_FILTERS, NOTIFICATION_TYPE_LABELS,
         type NotificationTarget, type NotificationType } from "@fms/shared";
import { type Href, router } from "expo-router";
import { type ReactNode, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { useSession } from "../session/Session";
import { colors, Empty, Screen, styles } from "../ui/components";

const TYPE_STYLES: Record<NotificationType, { icon: keyof typeof Ionicons.glyphMap; bg: string; fg: string }> = {
  sync: { icon: "sync-outline", bg: "#fee2e2", fg: "#b91c1c" },
  issue: { icon: "warning-outline", bg: "#ffedd5", fg: "#c2410c" },
  success: { icon: "checkmark", bg: "#dcfce7", fg: "#15803d" },
  info: { icon: "information-circle-outline", bg: "#dbeafe", fg: "#1d4ed8" },
};

/** Mobile screens for the notification actions (parcels have no mobile screen). */
const ROUTES: Partial<Record<NotificationTarget, Href>> = { tasks: "/tasks", sync: "/sync", finances: "/finance",
                                                               campaigns: "/campaign" };

export default function Notifications(): ReactNode {
  const { notifications, unread, markAllRead, markRead, farm } = useSession();
  const [filter, setFilter] = useState<NotificationType | "all">("all");
  const shown = filterNotifications(notifications, filter);

  return (
    <Screen>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={styles.muted}>{unread ? `${unread} non lue${unread > 1 ? "s" : ""}` : "Tout est lu"}</Text>
        {unread ? (
          <Pressable accessibilityRole="button" onPress={markAllRead} hitSlop={8} style={{ paddingVertical: 8 }}>
            <Text style={styles.link}>Tout marquer comme lu</Text>
          </Pressable>
        ) : null}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}
                  accessibilityLabel="Filtrer les notifications">
        {NOTIFICATION_FILTERS.map((f) => {
          const selected = f.id === filter;
          return (
            <Pressable key={f.id} accessibilityRole="button" accessibilityState={{ selected }}
                       onPress={() => setFilter(f.id)}
                       style={[styles.chip, selected && styles.chipSelected]}>
              <Text style={selected ? styles.primaryText : styles.chipText}>{f.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {shown.length === 0 ? (
        <Empty>{notifications.length === 0 ? "Aucune notification pour le moment."
          : "Aucune notification dans cette catégorie."}</Empty>
      ) : shown.map((n) => {
        const style = TYPE_STYLES[n.type];
        const route = n.action && n.farmId === farm?.id ? ROUTES[n.action.tab] : undefined;
        return (
          <View key={n.id} style={[styles.card, { flexDirection: "row", gap: 12 },
                                   !n.read && { borderColor: colors.primary, backgroundColor: "#f7fdf9" }]}>
            <View style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: style.bg, alignItems: "center",
                           justifyContent: "center" }}>
              <Ionicons name={style.icon} size={20} color={style.fg} />
            </View>
            <View style={{ flex: 1, gap: 4 }}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 8 }}>
                <Text style={{ color: style.fg, fontWeight: "700", fontSize: 12, flexShrink: 1 }}>
                  {NOTIFICATION_TYPE_LABELS[n.type]}{n.read ? "" : " · non lue"}
                </Text>
                <Text style={[styles.muted, { fontSize: 12 }]}>{formatAge(new Date(n.createdAt))}</Text>
              </View>
              <Text style={{ color: colors.text, fontSize: 15 }}>{n.text}</Text>
              {route && n.action ? (
                <Pressable accessibilityRole="button" hitSlop={6}
                           onPress={() => {
                             markRead(n.id);
                             router.push(route);
                           }}
                           style={{ alignSelf: "flex-start", paddingVertical: 8 }}>
                  <Text style={styles.link}>{n.action.label}</Text>
                </Pressable>
              ) : !n.read ? (
                <Pressable accessibilityRole="button" hitSlop={6} onPress={() => markRead(n.id)}
                           style={{ alignSelf: "flex-start", paddingVertical: 8 }}>
                  <Text style={styles.link}>Marquer comme lue</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        );
      })}
    </Screen>
  );
}
