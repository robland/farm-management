/** UX guarantees of the field screens: no duplicate entries, explicit confirmations. */

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
  localStorage.setItem("fms.refresh", "r");
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

describe("expenses", () => {
  const FINANCE = ["finance.view", "finance.transaction.create"];

  it("records a single transaction on a double click and shows it formatted", async () => {
    localStorage.setItem("fms.categories.org-1", JSON.stringify([{ id: "cat-1", kind: "expense", name: "Engrais" }]));
    const store = await openOffline(me("user-exp", FINANCE), [
      { type: "finance.account", id: "acc-1", data: { name: "Caisse", kind: "cash", currency: "XAF", is_active: true } },
    ]);
    // Only one account: preselected.
    await waitFor(() => expect((screen.getByLabelText("Compte") as HTMLSelectElement).value).toBe("acc-1"));
    fireEvent.change(screen.getByLabelText("Catégorie"), { target: { value: "cat-1" } });
    fireEvent.change(screen.getByLabelText("Montant (XAF)"), { target: { value: "15000" } });
    const submit = screen.getByRole("button", { name: "Enregistrer la dépense" });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(await screen.findByText(/Dépense de 15.000 XAF enregistrée sur cet appareil/)).toBeTruthy();
    expect(await opsOf(store, "finance.transaction")).toHaveLength(1);
    // Testing Library normalizes the narrow no-break space of the DOM, hence the regexes.
    expect(await screen.findByText(/^15.000 XAF$/)).toBeTruthy();

    // The sync screen speaks plain French, not entity codes.
    fireEvent.click(screen.getByRole("button", { name: "Synchronisation" }));
    expect(await screen.findByText(/^Dépense de 15.000 XAF$/)).toBeTruthy();
    expect(screen.queryByText(/finance\.transaction/)).toBeNull();
  });

  it("hides the entry form without the create permission", async () => {
    await openOffline(me("user-ro", ["finance.view"]));
    expect(await screen.findByText("Aucune transaction.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Enregistrer la dépense" })).toBeNull();
  });
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

    fireEvent.click(screen.getByRole("button", { name: "Déconnexion" }));
    const dialog = await screen.findByRole("dialog", { name: "Se déconnecter ?" });
    expect(dialog.textContent).toMatch(/restent sur cet appareil/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Annuler" }));
    expect(screen.getByText("Ferme Nord")).toBeTruthy();
  });

  it("lets a user with several farms pick one, with readable roles, or log out", async () => {
    localStorage.setItem("fms.refresh", "r");
    localStorage.setItem("fms.deviceId", "dev-1");
    localStorage.setItem("fms.me", JSON.stringify(me("user-multi", [], [
      { id: "farm-2", name: "Ferme Sud", organization_id: "org-1", role: "farm_manager", is_org_admin: false,
        permissions: [] }])));
    render(<App api={new ApiClient("/api/v1", async () => { throw new TypeError("Failed to fetch"); })} />);
    expect(await screen.findByText("Choisir une exploitation")).toBeTruthy();
    expect(screen.getByText("Gestionnaire d'exploitation")).toBeTruthy();
    expect(screen.getByText("Ouvrier")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Déconnexion" }));
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeTruthy();
  });
});
