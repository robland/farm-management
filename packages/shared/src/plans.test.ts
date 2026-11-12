import { describe, expect, it } from "vitest";

import {
  comparisonRows, durationError, fieldLabel, missingItems, monthColumns, parcelAvailability, percentToRatio,
  planRights, plantGap, ratioToPercent, resultsByParcel, timelineBar, versionActions,
} from "./index";

// Values are fictitious: they illustrate the rules, not agronomic recommendations.

describe("labels and rates", () => {
  it("names planting fields and phases in French", () => {
    expect(fieldLabel("planting_spec.row_spacing_m")).toBe("Écartement entre lignes");
    expect(fieldLabel("phases.nursery.duration_days")).toBe("Durée : Pépinière");
    expect(fieldLabel("allocations")).toBe("Parcelles");
    expect(fieldLabel("unknown_field")).toBe("unknown_field");
  });

  it("converts ratios and percentages exactly", () => {
    expect(ratioToPercent("0.7500")).toBe("75");
    expect(ratioToPercent(null)).toBe("");
    expect(percentToRatio("75,5")).toBe("0.755");
    expect(percentToRatio("")).toBeNull();
    expect(percentToRatio("75,123")).toBeUndefined(); // more precise than the server stores
    expect(percentToRatio("abc")).toBeUndefined();
  });

  it("accepts only whole positive durations, or an empty one to fill later", () => {
    expect(durationError("")).toBeUndefined();
    expect(durationError("25")).toBeUndefined();
    expect(durationError("2,5")).toBe("Nombre entier de jours (1 ou plus).");
    expect(durationError("0")).toBe("Nombre entier de jours (1 ou plus).");
  });
});

describe("version actions", () => {
  const technician = planRights(["plans.view", "plans.edit", "ai.use"]);
  const manager = planRights(["plans.view", "plans.edit", "plans.validate", "tasks.edit"]);
  const state = { complete: true, pendingSuggestions: 0, hasDraft: false, planClosed: false };

  it("lets a technician prepare but not validate", () => {
    expect(versionActions({ status: "draft" }, technician, state)).toMatchObject({ edit: true, validate: false });
  });

  it("blocks validation until AI suggestions are decided and the calculation is complete", () => {
    expect(versionActions({ status: "draft" }, manager, { ...state, pendingSuggestions: 3 }).validateBlocked)
      .toBe("3 suggestions IA à accepter, modifier ou rejeter.");
    expect(versionActions({ status: "draft" }, manager, { ...state, complete: false }).validateBlocked)
      .toBe("Le plan est incomplet : voir « À compléter ».");
    expect(versionActions({ status: "draft" }, manager, { ...state, complete: null }).validateBlocked)
      .toBe("Lancez le calcul avant de valider.");
    expect(versionActions({ status: "draft" }, manager, state).validateBlocked).toBeNull();
  });

  it("freezes a validated version: only a new version or task generation", () => {
    const actions = versionActions({ status: "validated" }, manager, state);
    expect(actions).toMatchObject({ edit: false, compute: false, validate: false, newVersion: true, generateTasks: true });
    expect(versionActions({ status: "validated" }, manager, { ...state, hasDraft: true }).newVersion).toBe(false);
  });
});

describe("missing data", () => {
  it("turns the calculation's missing list into a to-do list by section", () => {
    const items = missingItems([
      { scope: "parcel:p2", fields: ["row_spacing_m"], reason: "" },
      { scope: "calendar", fields: ["phases"] },
      { scope: "plan", fields: ["allocations"] },
      { scope: "parcel:p2", fields: ["nursery_success_rate"] },
    ], (id) => (id === "p2" ? "P-02" : id));
    expect(items.map((i) => [i.where, i.what, i.section])).toEqual([
      ["P-02", "Écartement entre lignes", "planting"],
      ["Calendrier", "Phases du calendrier", "calendar"],
      ["Plan", "Parcelles", "parcels"],
      ["P-02", "Réussite en pépinière", "planting"],
    ]);
  });
});

describe("results and occupation", () => {
  it("groups the engine records per parcel and reports the real/theoretical gap", () => {
    const density = { calc_type: "planting.density", scope: "parcel:p1", inputs: {}, formula: "", assumptions: [],
                      warnings: [], details: {},
                      outputs: { plant_count: { value: 3960, unit: "plants" },
                                 theoretical_plant_count: { value: 3700, unit: "plants" } } };
    const grouped = resultsByParcel([density, { ...density, calc_type: "calendar.phases", scope: "calendar" }]);
    expect(Object.keys(grouped)).toEqual(["p1"]);
    expect(plantGap(grouped.p1?.density)).toBe("+7,0 %");
  });

  it("computes the area left on a parcel, ignoring cancelled cycles and the plan itself", () => {
    const cycles = [
      { plan: "gombo", parcel: "p2", area_m2: "1000.0000", start_date: "2026-09-01", end_date: "2026-12-31", status: "active" },
      { plan: "old", parcel: "p2", area_m2: "500", start_date: "2026-09-01", end_date: "2026-12-31", status: "cancelled" },
      { plan: "piment", parcel: "p2", area_m2: "400", start_date: "2026-11-15", end_date: "2027-03-01", status: "planned" },
    ];
    expect(parcelAvailability("1200", cycles, "p2", { start: "2026-11-15", end: "2027-03-01" }, "piment"))
      .toEqual({ occupied: "1000", available: "200" });
    expect(parcelAvailability("1200", cycles, "p2", { start: "2027-01-01", end: "2027-03-01" }, "piment"))
      .toEqual({ occupied: "0", available: "1200" });
  });

  it("places cycles on the campaign timeline", () => {
    const window = { start: "2026-10-01", end: "2027-03-31" };
    expect(monthColumns(window).map((m) => m.label)).toEqual(["Oct.", "Nov.", "Déc.", "Janv.", "Févr.", "Mars"]);
    const bar = timelineBar(window, "2026-09-01", "2026-10-31");
    expect(bar?.left).toBe(0);
    expect(bar && Math.round(bar.width)).toBe(17);
    expect(timelineBar(window, "2027-05-01", "2027-06-01")).toBeNull();
  });

  it("describes the differences between two versions", () => {
    expect(comparisonRows([
      { section: "planting_spec", field: "plant_spacing_m", from: "0.6000", to: "0.5000" },
      { section: "phases", field: "nursery", from: 11, to: 25 },
      { section: "planting_spec", field: "germination_rate", from: "0.8", to: "0.75" },
      { section: "results", field: "plant_count", from: 3280, to: 3960 },
    ], (id) => id)).toEqual([
      { section: "Paramètres", field: "Écartement entre plants", from: "0,6", to: "0,5" },
      { section: "Calendrier", field: "Pépinière", from: "11 j", to: "25 j" },
      { section: "Paramètres", field: "Taux de germination", from: "80 %", to: "75 %" },
      // French thousands separator: narrow no-break space (U+202F).
      { section: "Résultats", field: "Nombre de plants", from: "3 280", to: "3 960" },
    ]);
  });
});
