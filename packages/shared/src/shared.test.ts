import { describe, expect, it } from "vitest";

import {
  describeError,
  describeOperation,
  formatAge,
  formatArea,
  formatDate,
  formatDateRange,
  formatMoney,
  formatNumber,
  groupTasks,
  isLate,
  operationDetails,
  pendingReports,
  roleLabel,
} from "./index";

const NB = " ";

describe("formatMoney", () => {
  it("groups thousands without centimes for XAF", () => {
    expect(formatMoney("15000", "XAF")).toBe(`15${NB}000 XAF`);
    expect(formatMoney("15000.00", "XAF")).toBe(`15${NB}000 XAF`);
    expect(formatMoney("1234567", "XOF")).toBe(`1${NB}234${NB}567 XOF`);
  });

  it("pads to the currency minor units with a decimal comma", () => {
    expect(formatMoney("1234.5", "EUR")).toBe(`1${NB}234,50 EUR`);
    expect(formatMoney("0.05", "USD")).toBe("0,05 USD");
  });

  it("never rounds and keeps values beyond float precision exact", () => {
    expect(formatMoney("12345678901234567.89", "EUR")).toBe(`12${NB}345${NB}678${NB}901${NB}234${NB}567,89 EUR`);
    expect(formatMoney("10.555", "EUR")).toBe("10,555 EUR");
  });

  it("handles signs, unknown currencies and garbage", () => {
    expect(formatMoney("-2500", "XAF")).toBe(`-2${NB}500 XAF`);
    expect(formatMoney("2500.5", "GBP")).toBe(`2${NB}500,5 GBP`);
    expect(formatMoney("abc", "XAF")).toBe("abc XAF");
  });
});

describe("number, area and date formatting", () => {
  it("formats numbers the French way", () => {
    expect(formatNumber("2500.75")).toBe(`2${NB}500,75`);
    expect(formatNumber(3)).toBe("3");
    expect(formatNumber("x")).toBe("x");
  });

  it("adds hectares from 1000 m²", () => {
    expect(formatArea("850")).toBe("850 m²");
    expect(formatArea("2500")).toBe(`2${NB}500 m² (0,25 ha)`);
    expect(formatArea(12000)).toBe(`12${NB}000 m² (1,2 ha)`);
  });

  it("formats calendar dates without time zone shifts", () => {
    expect(formatDate("2026-11-08")).toBe("8 nov. 2026");
    expect(formatDate("2026-02-01")).toBe("1 févr. 2026");
    expect(formatDate("not a date")).toBe("not a date");
    expect(formatDateRange("2026-11-08", "2026-11-08")).toBe("8 nov. 2026");
    expect(formatDateRange("2026-11-08", "2026-11-10")).toBe("8 nov. 2026 → 10 nov. 2026");
  });

  it("describes the age of the last sync", () => {
    const now = new Date("2026-11-08T12:00:00");
    expect(formatAge(new Date("2026-11-08T11:59:30"), now)).toBe("à l'instant");
    expect(formatAge(new Date("2026-11-08T11:55:00"), now)).toBe("il y a 5 min");
    expect(formatAge(new Date("2026-11-08T09:00:00"), now)).toBe("il y a 3 h");
    expect(formatAge(new Date("2026-11-06T09:30:00"), now)).toBe("le 6 nov. 2026 à 09:30");
  });
});

describe("labels", () => {
  it("translates default roles and keeps custom ones", () => {
    expect(roleLabel("farm_manager")).toBe("Gestionnaire d'exploitation");
    expect(roleLabel("pepiniériste")).toBe("pepiniériste");
    expect(roleLabel(null)).toBe("");
  });

  it("describes queued operations in plain words", () => {
    expect(describeOperation({ opType: "create", entityType: "finance.transaction",
      payload: { kind: "expense", amount: "15000", currency: "XAF" } })).toBe(`Dépense de 15${NB}000 XAF`);
    expect(describeOperation({ opType: "command", command: "task.change_status", entityType: "tasks.task",
      payload: { from: "todo", to: "in_progress" } })).toBe("Tâche : À faire → En cours");
    expect(describeOperation({ opType: "create", entityType: "tasks.task_report",
      payload: { completion: "complete" } })).toBe("Tâche terminée");
    expect(describeOperation({ opType: "create", entityType: "agronomy.observation",
      payload: { kind: "pest" } })).toBe("Observation : ravageur");
    expect(describeOperation({ opType: "create", entityType: "harvest.harvest_record",
      payload: { quantity: "120.5", unit: "kg" } })).toBe("Récolte de 120,5 kg");
    expect(describeOperation({ opType: "update", entityType: "fields.parcel", payload: {} }))
      .toBe("Modification : parcelle");
    expect(describeOperation({ opType: "delete", entityType: "x.unknown", payload: {} }))
      .toBe("Suppression : x.unknown");
  });

  it("lists payload details instead of raw JSON", () => {
    expect(operationDetails({ opType: "create", entityType: "fields.parcel",
      payload: { name: "Est", code: "PE-1", area_m2: "2500" } }))
      .toEqual(["Nom : Est", "Identifiant : PE-1", `Superficie : 2${NB}500 m² (0,25 ha)`]);
  });

  it("explains server refusals, server message first", () => {
    expect(describeError({ code: "permission_denied", message: "" }))
      .toBe("Vous n'avez pas l'autorisation de faire cette opération.");
    expect(describeError({ code: "business_rule_violation", message: "Surface dépassée." }))
      .toBe("Surface dépassée.");
    expect(describeError({ code: "validation_error", message: "Données invalides.",
      fieldErrors: { code: ["Déjà utilisé."], non_field_errors: ["Incohérent."] } }))
      .toBe("Données invalides. code : Déjà utilisé. · Incohérent.");
    expect(describeError({ code: "weird", message: "" })).toBe("Erreur : weird");
    expect(describeError(undefined)).toBe("");
  });
});

describe("tasks", () => {
  const task = (id: string, status: string, start: string, end: string) =>
    ({ id, status, planned_start_date: start, planned_end_date: end });
  const today = "2026-11-08";

  it("groups late, today, upcoming and finished tasks, sorted by date", () => {
    const groups = groupTasks([
      task("up", "todo", "2026-11-20", "2026-11-21"),
      task("now2", "in_progress", "2026-11-07", "2026-11-09"),
      task("late", "todo", "2026-11-01", "2026-11-05"),
      task("now1", "todo", "2026-11-05", "2026-11-08"),
      task("done", "done", "2026-11-01", "2026-11-02"),
      task("check", "to_verify", "2026-11-01", "2026-11-02"),
      task("gone", "cancelled", "2026-11-01", "2026-11-02"),
    ], today);
    expect(groups.late.map((t) => t.id)).toEqual(["late"]);
    expect(groups.today.map((t) => t.id)).toEqual(["now1", "now2"]);
    expect(groups.upcoming.map((t) => t.id)).toEqual(["up"]);
    expect(groups.finished.map((t) => t.id)).toEqual(["done", "check"]);
  });

  it("is late only when open and past its end date", () => {
    expect(isLate(task("a", "todo", "2026-11-01", "2026-11-07"), today)).toBe(true);
    expect(isLate(task("a", "todo", "2026-11-01", "2026-11-08"), today)).toBe(false);
    expect(isLate(task("a", "done", "2026-11-01", "2026-11-07"), today)).toBe(false);
  });

  it("finds tasks whose report is still queued, to block a duplicate report", () => {
    const pending = pendingReports([
      { task: "t1", _local: "pending" },
      { task: "t2", _local: "failed" },
      { task: "t3", _local: null },
      { task: "t4", _local: "synced" },
    ]);
    expect([...pending.entries()]).toEqual([["t1", "pending"], ["t2", "failed"]]);
  });
});
