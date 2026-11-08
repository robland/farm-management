import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import type { ReactNode } from "react";

import { HeaderActions } from "../features/header/HeaderActions";
import { SessionProvider } from "../session/Session";

export default function RootLayout(): ReactNode {
  return (
    <SessionProvider>
      <StatusBar style="dark" />
      {/* HeaderActions renders nothing until the user is signed in. */}
      <Stack screenOptions={{ headerRight: () => <HeaderActions /> }}>
        <Stack.Screen name="index" options={{ title: "Gestion agricole" }} />
        <Stack.Screen name="tasks" options={{ title: "Tâches" }} />
        <Stack.Screen name="observation" options={{ title: "Observation" }} />
        <Stack.Screen name="harvest" options={{ title: "Récolte" }} />
        <Stack.Screen name="expense" options={{ title: "Dépense" }} />
        <Stack.Screen name="sync" options={{ title: "Synchronisation" }} />
        <Stack.Screen name="notifications" options={{ title: "Notifications" }} />
        <Stack.Screen name="profile" options={{ title: "Profil", headerRight: () => null }} />
        <Stack.Screen name="create-farm" options={{ title: "Créer une exploitation" }} />
      </Stack>
    </SessionProvider>
  );
}
