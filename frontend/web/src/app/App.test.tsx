import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiClient } from "../api/client";
import { App } from "./App";

const ME = {
  user: { id: "user-app", full_name: "Awa", email: "awa@example.test", phone: null },
  organizations: [{ id: "org-1", name: "Org", is_org_admin: false }],
  farms: [{ id: "farm-1", name: "Ferme Nord", organization_id: "org-1", role: "farm_manager",
            is_org_admin: false, permissions: ["fields.view", "fields.edit", "tasks.view"] }],
};

type Handler = (method: string, path: string, body: unknown) => Response | "offline";

function fakeFetch(handler: Handler): typeof fetch {
  return async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    const result = handler(init?.method ?? "GET", url.replace("/api/v1", ""), body);
    if (result === "offline") throw new TypeError("Failed to fetch");
    return result;
  };
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("App", () => {
  it("shows a clear error on invalid credentials", async () => {
    const api = new ApiClient("/api/v1", fakeFetch(() =>
      json({ code: "validation_error", message: "", details: {}, field_errors: {} }, 400)));
    render(<App api={api} />);
    fireEvent.change(screen.getByLabelText("E-mail ou téléphone"), { target: { value: "x@y.z" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Identifiants invalides.");
  });

  it("logs in, picks a farm and records a parcel while offline", async () => {
    let offline = false;
    const api = new ApiClient("/api/v1", fakeFetch((method, path) => {
      if (path === "/auth/login/") {
        return json({ access: "a", refresh: "r", device_id: "dev-1", user_id: "user-app" });
      }
      if (offline) return "offline";
      if (path === "/me/") return json(ME);
      if (path.startsWith("/sync/pull/")) {
        return json({ changes: [], next_cursor: 0, has_more: false, purge: [], server_seq: 0 });
      }
      if (path === "/sync/push/" && method === "POST") return json({ results: [] });
      return json({}, 404);
    }));
    render(<App api={api} />);
    fireEvent.change(screen.getByLabelText("E-mail ou téléphone"), { target: { value: "awa@example.test" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    // Single farm: opened directly, on the tasks tab (field workers' first screen).
    expect(await screen.findByText("Aucune tâche planifiée.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Parcelles" }));
    expect(await screen.findByText("Aucune parcelle pour le moment.")).toBeTruthy();
    // Finance tab hidden: no finance permission.
    expect(screen.queryByRole("button", { name: "Dépenses" })).toBeNull();

    offline = true;
    fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Parcelle Est" } });
    fireEvent.change(screen.getByLabelText("Identifiant"), { target: { value: "PE-1" } });
    fireEvent.change(screen.getByLabelText("Superficie (m²)"), { target: { value: "2500" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText(/PE-1/)).toBeTruthy();
    expect(screen.getByText("En attente de synchronisation")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByRole("status")[0]?.textContent).toMatch(/1 en attente/));
  });

  it("validates the parcel form before recording", async () => {
    localStorage.setItem("fms.refresh", "r");
    localStorage.setItem("fms.deviceId", "dev-1");
    localStorage.setItem("fms.me", JSON.stringify(ME));
    localStorage.setItem("fms.farm", "farm-1");
    const api = new ApiClient("/api/v1", fakeFetch(() => "offline"));
    render(<App api={api} />);
    fireEvent.click(await screen.findByRole("button", { name: "Parcelles" }));
    fireEvent.click(await screen.findByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Nom obligatoire.")).toBeTruthy();
    expect(screen.getByText("Superficie en m², nombre positif.")).toBeTruthy();
  });
});
