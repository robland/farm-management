/** UX guarantees of the field screens: no duplicate entries, explicit confirmations (finances: features/finance). */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiClient } from "../api/client";
import type { Me } from "../api/types";
import { DexieStore } from "../storage/dexieStore";
import { App } from "./App";

const FARM = "farm-1";
const stores: DexieStore[] = [];

function me(userId: string, permissions: string[], extraFarms: Me["farms"] = []): Me {
  return {
    user: { id: userId, full_name: "Awa Diallo", email: null, phone: null },
    organizations: [{ id: "org-1", name: "Coopérative", is_org_admin: false }],
    farms: [{ id: FARM, name: "Ferme Nord", organization_id: "org-1", role: "worker", is_org_admin: false,
              permissions }, ...extraFarms],
  };
}

/** Opens the app with a cached session, offline, and local data already pulled. */
async function openOffline(profile: Me, entities: { type: string; id: string; data: object }[] = []) {
  localStorage.setItem("fms.session", "1");
  localStorage.setItem("fms.deviceId", "dev-1");
  localStorage.setItem("fms.me", JSON.stringify(profile));
  localStorage.setItem("fms.farm", FARM);
  const store = new DexieStore(profile.user.id);
  stores.push(store);
  await store.putEntities(entities.map((e) => ({
    entityType: e.type, entityId: e.id, farmId: FARM, version: 1, data: { id: e.id, ...e.data } })));
  render(<App api={new ApiClient("/api/v1", async () => { throw new TypeError("Failed to fetch"); })} />);
  return store;
}

const opsOf = async (store: DexieStore, entityType: string) =>
  (await store.listOperations(FARM)).filter((op) => op.entityType === entityType);

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(async () => {
  cleanup();
  for (const store of stores.splice(0)) await store.db.delete();
});

describe("tasks", () => {
  it("asks for confirmation, keeps notes and blocks a second report while it is queued", async () => {
    const store = await openOffline(me("user-task", ["tasks.view", "tasks.report"]), [
      { type: "tasks.task", id: "t-1", data: { title: "Sarclage", task_type: "weeding", status: "todo",
          planned_start_date: "2000-01-01", planned_end_date: "2000-01-02", parcel: null } },
    ]);
    expect(await screen.findByText("En retard (1)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Terminer" }));
    const dialog = screen.getByRole("dialog", { name: "Terminer la tâche ?" });
    fireEvent.change(within(dialog).getByLabelText(/Observations/), { target: { value: "Fait à moitié à la main" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminer" }));

    expect(await screen.findByText("Compte rendu : en attente de synchronisation")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Terminer" })).toBeNull();
    const reports = await opsOf(store, "tasks.task_report");
    expect(reports).toHaveLength(1);
    expect(reports[0]?.payload).toMatchObject({ task: "t-1", notes: "Fait à moitié à la main" });
  });

  it("cancels the finish dialog with Escape without recording anything", async () => {
    const store = await openOffline(me("user-esc", ["tasks.view", "tasks.report"]), [
      { type: "tasks.task", id: "t-2", data: { title: "Taille", task_type: "x", status: "todo",
          planned_start_date: "2999-01-01", planned_end_date: "2999-01-02", parcel: null } },
    ]);
    fireEvent.click(await screen.findByRole("button", { name: "Terminer" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await opsOf(store, "tasks.task_report")).toHaveLength(0);
  });
});

describe("session", () => {
  it("warns before logging out with unsent entries", async () => {
    await openOffline(me("user-out", ["fields.view", "fields.edit"]));
    fireEvent.change(await screen.findByLabelText("Nom"), { target: { value: "Est" } });
    fireEvent.change(screen.getByLabelText("Identifiant"), { target: { value: "P-1" } });
    fireEvent.change(screen.getByLabelText("Superficie (m²)"), { target: { value: "2500" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    // Shown on the row and in the total.
    expect(await screen.findAllByText(/2.500 m² \(0,25 ha\)/)).toHaveLength(2);

    // Logout lives in the profile menu.
    fireEvent.click(screen.getByRole("button", { name: "Profil : Awa Diallo" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Déconnexion" }));
    const dialog = await screen.findByRole("dialog", { name: "Se déconnecter ?" });
    expect(dialog.textContent).toMatch(/restent sur cet appareil/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Annuler" }));
    expect(screen.getByText("Ferme Nord")).toBeTruthy();
  });

  it("shows profile and notifications on the farm picker, with readable roles, and logs out", async () => {
    localStorage.setItem("fms.session", "1");
    localStorage.setItem("fms.deviceId", "dev-1");
    localStorage.setItem("fms.me", JSON.stringify(me("user-multi", [], [
      { id: "farm-2", name: "Ferme Sud", organization_id: "org-1", role: "farm_manager", is_org_admin: false,
        permissions: [] }])));
    render(<App api={new ApiClient("/api/v1", async () => { throw new TypeError("Failed to fetch"); })} />);
    expect(await screen.findByText("Choisir une exploitation")).toBeTruthy();
    expect(screen.getByText("Gestionnaire d'exploitation")).toBeTruthy();
    expect(screen.getByText("Ouvrier")).toBeTruthy();
    // Not an administrator of the organization: no creation.
    expect(screen.queryByRole("button", { name: /Créer une exploitation/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByText("Aucune notification pour le moment.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Profil : Awa Diallo" }));
    expect(screen.getByRole("menu", { name: "Profil" }).textContent).toMatch(/Awa Diallo/);
    fireEvent.click(screen.getByRole("menuitem", { name: "Déconnexion" }));
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeTruthy();
  });

  it("lets an organization administrator create a farm, then reloads the profile", async () => {
    const admin: Me = { ...me("user-admin", []), farms: [],
                        organizations: [{ id: "org-1", name: "Coopérative", is_org_admin: true },
                                        { id: "org-2", name: "Autre", is_org_admin: false }] };
    const created: unknown[] = [];
    let profile = admin;
    localStorage.setItem("fms.session", "1");
    localStorage.setItem("fms.deviceId", "dev-1");
    localStorage.setItem("fms.me", JSON.stringify(admin));
    const json = (data: unknown, status = 200) =>
      new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
    const api = new ApiClient("/api/v1", async (input, init) => {
      const url = String(input).replace("/api/v1", "");
      if (url === "/auth/refresh/") return json({ access: "a", refresh: "r" });
      if (url === "/me/") return json(profile);
      if (url === "/organizations/org-1/") {
        return json({ id: "org-1", country: "CM", default_currency: "XAF", default_timezone: "Africa/Douala" });
      }
      if (url === "/organizations/org-1/farms/" && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, string>;
        created.push(body);
        profile = { ...admin, farms: [{ id: "farm-new", name: body.name ?? "", organization_id: "org-1",
                                        role: null, is_org_admin: true, permissions: [] },
                                      { id: "farm-x", name: "Autre ferme", organization_id: "org-2",
                                        role: "worker", is_org_admin: false, permissions: [] }] };
        return json({ id: "farm-new" }, 201);
      }
      return json({}, 404);
    });
    render(<App api={api} />);
    // Only in the organization the user administers.
    const createButtons = await screen.findAllByRole("button", { name: /Créer une exploitation/ });
    expect(createButtons).toHaveLength(1);
    fireEvent.click(createButtons[0]!);
    const dialog = screen.getByRole("dialog", { name: "Créer une exploitation" });
    await waitFor(() => expect((within(dialog).getByLabelText("Pays") as HTMLInputElement).value).toBe("CM"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Créer l'exploitation" }));
    expect(await within(dialog).findByText("Nom obligatoire.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Nom"), { target: { value: "Ferme Est" } });
    fireEvent.change(within(dialog).getByLabelText("Code"), { target: { value: "ferme-est" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Créer l'exploitation" }));

    expect(await screen.findByText("Ferme Est")).toBeTruthy();
    expect(created).toEqual([{ name: "Ferme Est", code: "ferme-est", country: "CM", timezone: "Africa/Douala",
                               currency: "XAF" }]);
    expect(screen.getByRole("button", { name: "Notifications, 1 non lue" })).toBeTruthy();
  });
});
