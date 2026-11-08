import type { SyncEngine, SyncStore } from "@fms/sync-core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationsProvider, useNotifications } from "../notifications/NotificationsContext";
import { SyncProvider } from "./SyncContext";

function Texts(): ReactNode {
  const { notifications } = useNotifications();
  return <ul>{notifications.map((n) => <li key={n.id}>{n.type}: {n.text}</li>)}</ul>;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("SyncProvider", () => {
  it("turns a local synchronization failure into a visible notification, once", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const engine = {
      sync: vi.fn().mockRejectedValue(new Error("QuotaExceededError")),
      view: vi.fn().mockResolvedValue([]),
      stats: vi.fn().mockResolvedValue({ pending: 0, syncing: 0, synced: 0, failed: 0, conflict: 0 }),
    } as unknown as SyncEngine;
    const store = { listOperations: vi.fn().mockResolvedValue([]) } as unknown as SyncStore;
    render(
      <NotificationsProvider userId="u-err">
        <SyncProvider engine={engine} store={store} farmId="f" onAuthRequired={() => undefined}>
          <Texts />
        </SyncProvider>
      </NotificationsProvider>,
    );
    expect(await screen.findByText(/sync: La synchronisation a échoué sur cet appareil \(QuotaExceededError\)/))
      .toBeTruthy();
    expect(console.error).toHaveBeenCalled();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
});
