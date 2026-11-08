import { describe, expect, it } from "vitest";

import { hasErrors, validateExpense, validateParcel } from "./validation";

describe("validateParcel", () => {
  it("accepts a valid parcel with a decimal comma", () => {
    expect(hasErrors(validateParcel({ name: "Nord", code: "P1", area_m2: "1 000,5", soil_ph: "6,5" })))
      .toBe(false);
  });

  it("reports each invalid field", () => {
    const errors = validateParcel({ name: " ", code: "", area_m2: "-3", soil_ph: "15" });
    expect(Object.keys(errors).sort()).toEqual(["area_m2", "code", "name", "soil_ph"]);
  });
});

describe("validateExpense", () => {
  const base = { account: "a", category: "c", amount: "15000", business_date: "2026-11-08",
                 description: "" };

  it("accepts whole francs CFA", () => {
    expect(hasErrors(validateExpense(base, "XAF", "2026-11-08"))).toBe(false);
  });

  it("refuses cents in XAF but accepts them in EUR", () => {
    expect(validateExpense({ ...base, amount: "10,50" }, "XAF", "2026-11-08").amount)
      .toMatch(/entier/);
    expect(validateExpense({ ...base, amount: "10,50" }, "EUR", "2026-11-08").amount).toBeUndefined();
  });

  it("refuses future dates, missing fields and unknown currencies", () => {
    const errors = validateExpense({ ...base, account: "", category: "", business_date: "2026-12-01" },
                                   "XAF", "2026-11-08");
    expect(Object.keys(errors).sort()).toEqual(["account", "business_date", "category"]);
    expect(validateExpense(base, "ZZZ", "2026-11-08").amount).toMatch(/Devise/);
  });
});
