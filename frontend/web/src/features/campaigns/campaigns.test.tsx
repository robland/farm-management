/** Campaigns tab (PLANNING_SCENARIOS.md S1 to S8, S11). Values are fictitious, not recommendations. */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiClient } from "../../api/client";
import type { Me } from "../../api/types";
import { App } from "../../app/App";
import { DexieStore } from "../../storage/dexieStore";

const FARM = "farm-1";
const stores: DexieStore[] = [];
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
type Call = { method: string; path: string; body: unknown; headers: Record<string, string> };

function me(permissions: string[]): Me {
  return { user: { id: `u-${permissions.length}-${Math.random()}`, full_name: "Awa Diallo", email: null, phone: null },
           organizations: [{ id: "org-1", name: "Coopérative", is_org_admin: false }],
           farms: [{ id: FARM, name: "Ferme Nord", organization_id: "org-1", role: "agri_manager", is_org_admin: false, permissions }] };
}

const CAMPAIGN = { type: "production_plans.campaign", id: "camp-1",
                   data: { name: "Saison sèche 2026", start_date: "2026-10-01", end_date: "2027-03-31", status: "active" } };
const PARCELS = [
  { type: "fields.parcel", id: "p1", data: { name: "Nord", code: "P-01", area_m2: "2000.0000" } },
  { type: "fields.parcel", id: "p2", data: { name: "Bas-fond", code: "P-02", area_m2: "1200.0000" } },
];
const density = { id: "c1", calc_type: "planting.density", scope: "parcel:p1", engine_version: "1.4", formula: "Nr = lignes × plants/ligne × k",
  inputs: { row_spacing_m: { value: "1.0000", unit: "m" } }, assumptions: ["Disposition rectangulaire."], warnings: [], details: {},
  outputs: { plantable_area_m2: { value: "1850.0000", unit: "m2" }, plant_count: { value: 3960, unit: "plants" },
             theoretical_plant_count: { value: 3700, unit: "plants" }, theoretical_density_per_m2: { value: "2.0000", unit: "plants/m2" },
             theoretical_density_per_ha: { value: "20000.00", unit: "plants/ha" }, real_density_per_m2: { value: "1.9800", unit: "plants/m2" },
             real_density_per_ha: { value: "19800.00", unit: "plants/ha" }, real_density_on_plantable_per_m2: { value: "2.1405", unit: "" } },
  created_at: "2026-11-05T08:12:00Z" };

function version(id: string, plan: string, status: string, extra: object = {}) {
  return { type: "production_plans.plan_version", id, data: {
    plan, number: 1, status, origin: "manual", based_on: null, technical_data_set: null, planned_start_date: "2026-11-15",
    planned_end_date: "2027-03-01", target_yield_kg_per_ha: null, objectives: "", constraints_notes: "", change_note: "",
    validated_by: null, validated_at: null, planting_spec: {}, allocations: [], phases: [], provenances: [], calculations: [],
    version: 4, ...extra } };
}

async function open(profile: Me, entities: { type: string; id: string; data: object }[], routes?: (c: Call) => Response | undefined) {
  localStorage.setItem("fms.session", "1");
  localStorage.setItem("fms.deviceId", "dev-1");
  localStorage.setItem("fms.me", JSON.stringify(profile));
  localStorage.setItem("fms.farm", FARM);
  sessionStorage.setItem("fms.tab", "campaigns");
  const store = new DexieStore(profile.user.id);
  stores.push(store);
  await store.putEntities(entities.map((e) => ({ entityType: e.type, entityId: e.id, farmId: FARM, version: 1,
                                                 data: { id: e.id, ...e.data } })));
  const calls: Call[] = [];
  render(<App api={new ApiClient("/api/v1", async (input, init) => {
    if (!routes) throw new TypeError("Failed to fetch");
    const path = String(input).replace("/api/v1", "");
    const call = { method: init?.method ?? "GET", path, body: init?.body ? JSON.parse(String(init.body)) : undefined,
                   headers: (init?.headers ?? {}) as Record<string, string> };
    calls.push(call);
    if (path === "/auth/refresh/") return json({ access: "a" });
    if (path === "/me/") return json(profile);
    if (path.startsWith("/sync/pull/")) return json({ changes: [], next_cursor: 0, has_more: false, purge: [], server_seq: 0 });
    if (path === "/sync/push/") return json({ results: [] });
    return routes(call) ?? json({ count: 0, results: [] });
  })} />);
  return { calls };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(async () => {
  cleanup();
  for (const store of stores.splice(0)) await store.db.delete();
});

const VALIDATED_PLAN = { type: "production_plans.plan", id: "plan-1", data: {
  campaign: "camp-1", variety: "v1", variety_name: "Tomate V-01", name: "Tomate · P-01", status: "in_progress",
  current_version: "ver-1", version: 2 } };
const VALIDATED = version("ver-1", "plan-1", "validated", {
  validated_at: "2026-11-05T09:00:00Z", calculations: [density],
  allocations: [{ parcel: "p1", allocated_area_m2: "2000.0000", non_plantable_area_m2: "150.0000", plot_length_m: "50.000",
                  plot_width_m: "40.000", notes: "" }],
  phases: [{ phase_code: "transplanting", sequence: 1, duration_days: 3, start_date: "2026-11-07", end_date: "2026-11-09" }] });

describe("offline consultation", () => {
  it("lists the campaign's plans and shows the engine's results with their traceability", async () => {
    await open(me(["plans.view"]), [CAMPAIGN, ...PARCELS, VALIDATED_PLAN, VALIDATED,
      { type: "production_plans.crop_cycle", id: "cy1", data: { plan: "plan-1", plan_version: "ver-1", parcel: "p1",
        area_m2: "2000.0000", start_date: "2026-10-06", end_date: "2027-03-19", status: "active" } }]);
    expect(await screen.findByText("Tomate · P-01")).toBeTruthy();
    expect(screen.getByText("Occupation des parcelles")).toBeTruthy();
    // No right to edit: no creation buttons.
    expect(screen.queryByRole("button", { name: "+ Nouveau plan" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Tomate · P-01/ }));
    const results = await screen.findByRole("region", { name: "Résultats P-01" });
    expect(within(results).getByText(/^3.960$/)).toBeTruthy();
    expect(within(results).getByText(/théorique : 3.700 \(\+7,0 %\)/)).toBeTruthy();
    expect(within(results).getByText("Traçabilité : densité et nombre de plants")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Générer les tâches" })).toBeNull();
  });
});

describe("draft editor", () => {
  const MANAGER = ["plans.view", "plans.edit", "plans.validate", "tasks.edit", "ai.use"];
  const DRAFT_PLAN = { type: "production_plans.plan", id: "plan-2", data: {
    campaign: "camp-1", variety: "v2", variety_name: "Piment V-04", name: "Piment · P-02", status: "draft",
    current_version: null, version: 1 } };
  const DRAFT = version("ver-2", "plan-2", "draft", {
    allocations: [{ parcel: "p2", allocated_area_m2: "400.0000", non_plantable_area_m2: "40.0000", plot_length_m: null,
                    plot_width_m: null, notes: "" }],
    planting_spec: { planting_method: "transplanting", layout: "single_row", plant_spacing_m: "0.4000", germination_rate: "0.7500" },
    provenances: [{ field_path: "planting_spec.germination_rate", source_kind: "document", technical_data_item: "i1", note: "" },
                  { field_path: "planting_spec.plant_spacing_m", source_kind: "user_input", technical_data_item: null, note: "" }] });
  const GOMBO_CYCLE = { type: "production_plans.crop_cycle", id: "cy-g", data: { plan: "gombo", plan_version: "vg", parcel: "p2",
    area_m2: "1000.0000", start_date: "2026-09-01", end_date: "2026-12-31", status: "active" } };

  it("warns of a parcel conflict, lists what is missing and blocks validation until complete", async () => {
    const { calls } = await open(me(MANAGER), [CAMPAIGN, ...PARCELS, DRAFT_PLAN, DRAFT, GOMBO_CYCLE], (call) => {
      if (call.path === "/farms/farm-1/plan-versions/ver-2/compute/") {
        return json({ complete: false, missing: [{ scope: "parcel:p2", fields: ["row_spacing_m", "nursery_success_rate"], reason: "" }],
                      errors: [], totals: {} });
      }
      if (call.path === "/farms/farm-1/plan-versions/ver-2/") return json(DRAFT.data && { id: "ver-2", ...DRAFT.data });
      if (call.path === "/farms/farm-1/plan-versions/ver-2/prefill/") {
        return json({ filled: [], needs_user_choice: ["row_spacing_m"], version: { id: "ver-2", ...DRAFT.data, version: 5 } });
      }
      return undefined;
    });
    fireEvent.click(await screen.findByRole("button", { name: /Piment · P-02/ }));
    // S5, announced while preparing: 1 000 m² already used out of 1 200 m².
    expect(await screen.findByText("P-02 est déjà occupée sur cette période.")).toBeTruthy();
    // Values show where they come from.
    const planting = screen.getByRole("form", { name: "Paramètres de plantation" });
    expect((within(planting).getByLabelText("Taux de germination (%)") as HTMLInputElement).value).toBe("75");
    // On the germination field, and in the legend of the badges.
    expect(within(planting).getAllByText("Source documentaire")).toHaveLength(2);
    expect(within(planting).getAllByText("Saisie utilisateur")).toHaveLength(2);
    const validate = screen.getByRole("button", { name: "Valider le plan" }) as HTMLButtonElement;
    await waitFor(() => expect(validate.disabled).toBe(true));
    expect(screen.getByText(/Lancez « Calculer »/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Calculer" }));
    const todo = await screen.findByRole("complementary", { name: "À compléter" });
    expect(await within(todo).findByText("À compléter (2)")).toBeTruthy();
    expect(within(todo).getByText(/Écartement entre lignes/)).toBeTruthy();
    expect(within(todo).getByText(/Réussite en pépinière/)).toBeTruthy();
    expect(validate.disabled).toBe(true);

    // S2: a documented range is left to the user.
    fireEvent.click(screen.getByRole("button", { name: "Pré-remplir depuis la fiche" }));
    expect(await screen.findByText("La fiche donne une plage : le système ne choisit pas à votre place.")).toBeTruthy();
    expect(calls.find((c) => c.path.endsWith("/prefill/"))?.headers["If-Match"]).toBe("4");
  });

  it("blocks validation while an AI suggestion is undecided, then sends the decision", async () => {
    const AI_DRAFT = version("ver-3", "plan-3", "draft", { origin: "ai_draft",
      allocations: [{ parcel: "p1", allocated_area_m2: "1500.0000", non_plantable_area_m2: "100.0000", plot_length_m: null,
                      plot_width_m: null, notes: "" }] });
    let decided = false;
    const { calls } = await open(me(MANAGER), [CAMPAIGN, ...PARCELS, AI_DRAFT,
      { type: "production_plans.plan", id: "plan-3", data: { campaign: "camp-1", variety: "v3", variety_name: "Oignon V-02",
                                                             name: "Oignon · P-03", status: "draft", current_version: null, version: 1 } }],
    (call) => {
      if (call.path.startsWith("/farms/farm-1/ai/plan-drafts/")) {
        return json({ count: 1, results: [{ id: "run-1", status: "succeeded", plan_version: "ver-3", missing_info: [], error_message: "",
          usage: [], created_at: "2026-11-08T16:05:00Z",
          suggestions: [{ id: "s1", plan_version: "ver-3", field_path: "planting_spec.plant_spacing_m", value: "0.1",
                          rationale: "Valeur courante pour ce type de culture", status: decided ? "accepted" : "suggested" }] }] });
      }
      if (call.path === "/farms/farm-1/ai/suggestions/s1/decide/") {
        decided = true;
        return json({ id: "s1", status: "accepted" });
      }
      if (call.path === "/farms/farm-1/plan-versions/ver-3/") return json({ id: "ver-3", ...AI_DRAFT.data });
      if (call.path === "/farms/farm-1/plan-versions/ver-3/compute/") return json({ complete: true, missing: [], errors: [], totals: {} });
      return undefined;
    });
    fireEvent.click(await screen.findByRole("button", { name: /Oignon · P-03/ }));
    expect(await screen.findByText("Propositions de l'IA (1 à trancher)")).toBeTruthy();
    expect(screen.getByText(/Aucune citation retrouvée dans la fiche/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Calculer" }));
    expect(await screen.findByText(/Validation bloquée : 1 suggestion IA à accepter, modifier ou rejeter\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accepter" }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith("/decide/"))?.body).toEqual({ decision: "accept" }));
    expect(await screen.findByText("Acceptée")).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "Valider le plan" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("generates the tasks of a validated version and reports what was kept", async () => {
    const { calls } = await open(me(MANAGER), [CAMPAIGN, ...PARCELS, VALIDATED_PLAN, VALIDATED], (call) =>
      (call.path === "/farms/farm-1/tasks/generate/"
        ? json({ created: 0, unchanged: 0, replanned: 6, cancelled: 0, kept: 2 }) : undefined));
    fireEvent.click(await screen.findByRole("button", { name: /Tomate · P-01/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Générer les tâches" }));
    expect(await screen.findByText("Tâches mises à jour depuis la version 1")).toBeTruthy();
    expect(screen.getByText(/Conservées \(commencées ou terminées\)/).textContent).toMatch(/2/);
    expect(calls.find((c) => c.path === "/farms/farm-1/tasks/generate/")?.body).toEqual({ plan_version: "ver-1" });
    // A validated version is frozen: no editor fields.
    expect(screen.queryByRole("form", { name: "Paramètres de plantation" })).toBeNull();
  });
});
