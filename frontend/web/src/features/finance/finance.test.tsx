/** Finances tab: offline entry, rights, validation workflow (FR-070 to FR-077, Q35). */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiClient } from "../../api/client";
import type { Me } from "../../api/types";
import { App } from "../../app/App";
import { DexieStore } from "../../storage/dexieStore";

const FARM = "farm-1";
const stores: DexieStore[] = [];

function me(userId: string, permissions: string[]): Me {
  return {
    user: { id: userId, full_name: "Awa Diallo", email: null, phone: null },
    organizations: [{ id: "org-1", name: "Coopérative", is_org_admin: false }],
    farms: [{ id: FARM, name: "Ferme Nord", organization_id: "org-1", role: "finance_manager", is_org_admin: false,
              permissions }],
  };
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

type Call = { method: string; path: string; body: unknown; headers: Record<string, string> };

/** Opens the app on the Finances tab, with local data already pulled; `routes` answers online. */
async function open(profile: Me, entities: { type: string; id: string; data: object }[],
                    routes?: (call: Call) => Response | undefined) {
  localStorage.setItem("fms.session", "1");
  localStorage.setItem("fms.deviceId", "dev-1");
  localStorage.setItem("fms.me", JSON.stringify(profile));
  localStorage.setItem("fms.farm", FARM);
  sessionStorage.setItem("fms.tab", "finances");
  const store = new DexieStore(profile.user.id);
  stores.push(store);
  await store.putEntities(entities.map((e) => ({
    entityType: e.type, entityId: e.id, farmId: FARM, version: 3, data: { id: e.id, ...e.data } })));
  const calls: Call[] = [];
  const api = new ApiClient("/api/v1", async (input, init) => {
    if (!routes) throw new TypeError("Failed to fetch");
    const path = String(input).replace("/api/v1", "");
    const call = { method: init?.method ?? "GET", path, body: init?.body ? JSON.parse(String(init.body)) : undefined,
                   headers: (init?.headers ?? {}) as Record<string, string> };
    calls.push(call);
    if (path === "/auth/refresh/") return json({ access: "a" });
    if (path === "/me/") return json(profile);
    if (path.startsWith("/sync/pull/")) {
      return json({ changes: [], next_cursor: 0, has_more: false, purge: [], server_seq: 0 });
    }
    if (path === "/sync/push/") {
      const ops = (call.body as { operations: { op_id: string }[] }).operations;
      return json({ results: ops.map((o) => ({ op_id: o.op_id, status: "applied", entity_version: 1 })) });
    }
    return routes(call) ?? json({}, 404);
  });
  render(<App api={api} />);
  return { store, calls };
}

const ACCOUNT = { type: "finance.account", id: "acc-1",
                  data: { name: "Trésorerie", kind: "bank", role: "main", currency: "XAF", is_active: true } };
const CATEGORIES = { data: { count: 1, results: [{ id: "cat-1", kind: "expense", name: "Engrais" }] },
                     at: "2026-11-09T08:00:00Z" };

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(async () => {
  cleanup();
  for (const store of stores.splice(0)) await store.db.delete();
});

describe("offline entry", () => {
  it("records a single expense on a double click, shows it in the journal and the sync screen", async () => {
    localStorage.setItem("fms.categories.org-1", JSON.stringify(CATEGORIES));
    const { store } = await open(me("u-exp", ["finance.view", "finance.transaction.create"]), [ACCOUNT]);
    fireEvent.click(await screen.findByRole("button", { name: "+ Nouvelle opération" }));
    const form = screen.getByRole("form", { name: "Nouvelle opération" });
    // A single possible account is preselected.
    await waitFor(() => expect((within(form).getByLabelText("Compte débité") as HTMLSelectElement).value).toBe("acc-1"));
    fireEvent.change(within(form).getByLabelText("Catégorie"), { target: { value: "cat-1" } });
    fireEvent.change(within(form).getByLabelText("Montant (XAF)"), { target: { value: "15000,5" } });
    fireEvent.click(within(form).getByRole("button", { name: "Enregistrer la dépense" }));
    expect(await within(form).findByText("Montant entier en XAF (pas de centimes).")).toBeTruthy();
    fireEvent.change(within(form).getByLabelText("Montant (XAF)"), { target: { value: "15 000" } });
    const submit = within(form).getByRole("button", { name: "Enregistrer la dépense" });
    fireEvent.click(submit);
    fireEvent.click(submit);

    // The journal opens with the entry, flagged as not sent yet.
    expect(await screen.findByText("En attente de synchronisation")).toBeTruthy();
    expect(screen.getAllByText(/^−15.000 XAF$/).length).toBeGreaterThan(0);
    const ops = (await store.listOperations(FARM)).filter((op) => op.entityType === "finance.transaction");
    expect(ops).toHaveLength(1);
    expect(ops[0]?.payload).toMatchObject({ kind: "expense", account: "acc-1", category: "cat-1", amount: "15000",
                                            currency: "XAF" });
    fireEvent.click(screen.getByRole("button", { name: "Notifications, 1 non lue" }));
    expect(screen.getByText(/Dépense de 15.000 XAF enregistrée sur cet appareil/)).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });

    // The sync screen speaks plain French, not entity codes.
    fireEvent.click(screen.getByRole("button", { name: "Synchronisation" }));
    expect(await screen.findByText(/^Dépense de 15.000 XAF$/)).toBeTruthy();
    expect(screen.queryByText(/finance\.transaction/)).toBeNull();
  });

  it("refuses a transfer between accounts of different currencies before saving", async () => {
    const { store } = await open(me("u-trf", ["finance.view", "finance.transaction.create"]), [ACCOUNT,
      { type: "finance.account", id: "acc-eur", data: { name: "Euro", kind: "bank", role: "operating",
                                                        currency: "EUR", is_active: true } }]);
    fireEvent.click(await screen.findByRole("button", { name: "+ Nouvelle opération" }));
    const form = screen.getByRole("form", { name: "Nouvelle opération" });
    fireEvent.click(within(form).getByRole("radio", { name: "Transfert" }));
    fireEvent.change(within(form).getByLabelText("Depuis"), { target: { value: "acc-1" } });
    // The other currency is not even offered as a target.
    const targets = within(within(form).getByLabelText("Vers")).queryAllByRole("option").map((o) => o.textContent);
    expect(targets).toEqual(["Choisir…"]);
    fireEvent.change(within(form).getByLabelText("Montant (XAF)"), { target: { value: "1000" } });
    fireEvent.click(within(form).getByRole("button", { name: "Enregistrer le transfert" }));
    expect(await within(form).findByText("Compte destinataire obligatoire.")).toBeTruthy();
    expect(await store.listOperations(FARM)).toHaveLength(0);
  });
});

describe("rights", () => {
  it("hides the entry button for a reader", async () => {
    await open(me("u-ro", ["finance.view"]), [ACCOUNT]);
    expect(await screen.findByRole("navigation", { name: "Finances" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "+ Nouvelle opération" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Journal" }));
    expect(await screen.findByText("Aucune opération.")).toBeTruthy();
  });

  it("shows a contributor only their member account (Q35)", async () => {
    await open(me("u-contrib", ["farm.view", "finance.funding.create"]), []);
    expect(await screen.findByText("Vous n'avez pas encore de compte de membre.")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Finances" });
    expect(within(nav).queryByRole("button", { name: "Vue d'ensemble" })).toBeNull();
    expect(within(nav).queryByRole("button", { name: "Budgets" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Nouvelle opération" })).toBeNull();
  });
});

describe("online", () => {
  const SUBMITTED = { type: "finance.transaction", id: "tx-1", data: {
    kind: "expense", status: "submitted", business_date: "2026-11-08", amount: "48000.0000", currency: "XAF",
    description: "Engrais organique", category: "cat-1", possible_duplicate: true, version: 3,
    entries: [{ account: "acc-1", amount: "-48000.0000" }] } };

  it("shows balances sent as JSON numbers exactly, and validates with If-Match", async () => {
    const { calls } = await open(me("u-val", ["finance.view", "finance.transaction.validate"]), [ACCOUNT, SUBMITTED],
      (call) => {
        if (call.path === "/farms/farm-1/treasury-accounts/balances/") {
          return json([{ account: "acc-1", name: "Trésorerie", role: "main", holder: null, currency: "XAF",
                         balance: 1840000, pending: -48000, provisional_balance: 1792000, is_active: true }]);
        }
        if (call.path.startsWith("/farms/farm-1/transactions/treasury/")) {
          return json({ currencies: { XAF: { opening_balance: 1500000, periods: [
            { period_start: "2026-11-02", inflows: 580000, outflows: 592500, investments: 0, fundings: 0,
              repayments: 0, transfers: 0, opening_entries: 0, net: -12500, closing_balance: 1487500 }] } } });
        }
        if (call.method === "POST" && call.path.endsWith("/validate/")) return json({ id: "tx-1" });
        if (call.path.endsWith("/revisions/")) return json([]);
        return undefined;
      });
    expect(await screen.findByText(/^1.840.000 XAF$/)).toBeTruthy();
    // Campaign result = income − campaign expenses, exact.
    expect(await screen.findByText(/^−12.500 XAF$/)).toBeTruthy();
    expect(screen.getByText("À valider (1)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Examiner" }));

    const detail = await screen.findByRole("complementary", { name: "Détail : Engrais organique" });
    expect(within(detail).getByText(/Doublon possible\./)).toBeTruthy();
    fireEvent.click(within(detail).getByRole("button", { name: "Valider" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/farms/farm-1/transactions/tx-1/validate/")).toBe(true));
    const validate = calls.find((c) => c.path.endsWith("/validate/"));
    expect(validate?.method).toBe("POST");
    expect(validate?.headers["If-Match"]).toBe("3");
  });

  it("asks for a reason before rejecting", async () => {
    const { calls } = await open(me("u-rej", ["finance.view", "finance.transaction.validate"]), [ACCOUNT, SUBMITTED],
      (call) => (call.method === "POST" && call.path.endsWith("/reject/") ? json({ id: "tx-1" })
        : call.path.endsWith("/revisions/") ? json([]) : undefined));
    fireEvent.click(await screen.findByRole("button", { name: "Journal" }));
    fireEvent.click(await screen.findByRole("button", { name: /Engrais organique/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Rejeter…" }));
    const dialog = screen.getByRole("alertdialog", { name: "Rejeter cette opération ?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rejeter" }));
    expect(within(dialog).getByText("Indiquez le motif.")).toBeTruthy();
    expect(calls.some((c) => c.path.endsWith("/reject/"))).toBe(false);
    fireEvent.change(within(dialog).getByLabelText("Motif (obligatoire)"), { target: { value: "Déjà saisie" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rejeter" }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith("/reject/"))?.body).toEqual({ reason: "Déjà saisie" }));
  });
});
