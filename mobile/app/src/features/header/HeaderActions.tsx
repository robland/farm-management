import { initials } from "@fms/shared";
import { router } from "expo-router";
import type { ReactNode } from "react";
import { View } from "react-native";

import { useSession } from "../../session/Session";
import { Avatar, IconButton } from "../../ui/components";

/** Bell and profile, in the header of every screen once signed in (farm picker included). */
export function HeaderActions(): ReactNode {
  const { me, unread } = useSession();
  if (!me) return null;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
      <IconButton label="Notifications" icon="notifications-outline" badge={unread}
                  onPress={() => router.push("/notifications")} />
      <Avatar initials={initials(me.user.full_name)} label={`Profil : ${me.user.full_name}`}
              onPress={() => router.push("/profile")} />
    </View>
  );
}
