import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import type { ReactNode } from "react";

import { SessionProvider } from "../session/Session";

export default function RootLayout(): ReactNode {
  return (
    <SessionProvider>
      <StatusBar style="dark" />
      <Stack>
        <Stack.Screen name="index" options={{ title: "Gestion agricole" }} />
        <Stack.Screen name="tasks" options={{ title: "Tâches" }} />
        <Stack.Screen name="observation" options={{ title: "Observation" }} />
        <Stack.Screen name="harvest" options={{ title: "Récolte" }} />
        <Stack.Screen name="expense" options={{ title: "Dépense" }} />
        <Stack.Screen name="sync" options={{ title: "Synchronisation" }} />
      </Stack>
    </SessionProvider>
  );
}
