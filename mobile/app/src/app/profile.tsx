import Ionicons from "@expo/vector-icons/Ionicons";
import { initials, roleLabel } from "@fms/shared";
import { router } from "expo-router";
import type { ReactNode } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { useSession } from "../session/Session";
import { colors, Empty, Screen, styles } from "../ui/components";

export default function Profile(): ReactNode {
  const { me, farm, logout, countUnsent, pickFarm } = useSession();
  if (!me) return <Empty>Vous n'êtes pas connecté.</Empty>;

  const leave = async () => {
    await logout();
    router.dismissTo("/");
  };

  // Sensitive operation: explicit confirmation when entries are not sent yet (CLAUDE.md §7).
  const confirmLogout = async () => {
    const unsent = await countUnsent();
    if (!unsent) return void leave();
    Alert.alert("Se déconnecter ?",
      `Saisies pas encore envoyées : ${unsent}. Elles restent sur ce téléphone et seront envoyées à votre `
      + "prochaine connexion avec ce même compte.", [
        { text: "Annuler", style: "cancel" },
        { text: "Se déconnecter", style: "destructive", onPress: () => void leave() },
      ]);
  };

  const role = farm ? (farm.is_org_admin && !farm.role ? "Administrateur de l'organisation" : roleLabel(farm.role))
    : "";
  const contact = me.user.email ?? me.user.phone;
  return (
    <Screen>
      <View style={[styles.card, { flexDirection: "row", alignItems: "center", gap: 14 }]}>
        <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: colors.primaryDark,
                       alignItems: "center", justifyContent: "center" }}>
          <Text style={{ color: "white", fontWeight: "700", fontSize: 20 }}>{initials(me.user.full_name)}</Text>
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={{ fontSize: 18, fontWeight: "700", color: colors.text }}>{me.user.full_name}</Text>
          {contact ? <Text style={styles.muted}>{contact}</Text> : null}
          {farm ? <Text style={styles.muted}>{[role, farm.name].filter(Boolean).join(" · ")}</Text> : null}
        </View>
      </View>
      {farm && me.farms.length > 1 ? (
        <Pressable accessibilityRole="button" style={({ pressed }) => [styles.card, styles.menuRow, pressed && styles.pressed]}
                   onPress={() => {
                     pickFarm(null);
                     router.dismissTo("/");
                   }}>
          <Ionicons name="swap-horizontal-outline" size={20} color={colors.text} />
          <Text style={{ flex: 1, fontSize: 16, color: colors.text }}>Changer d'exploitation</Text>
        </Pressable>
      ) : null}
      <Pressable accessibilityRole="button" style={({ pressed }) => [styles.card, styles.menuRow, pressed && styles.pressed]}
                 onPress={() => void confirmLogout()}>
        <Ionicons name="power" size={20} color={colors.danger} />
        <Text style={{ flex: 1, fontSize: 16, color: colors.danger, fontWeight: "600" }}>Déconnexion</Text>
      </Pressable>
    </Screen>
  );
}
