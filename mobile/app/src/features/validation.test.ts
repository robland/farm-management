import { describe, expect, it } from "vitest";

import { todayIso, validateAmount, validateQuantity, validateSeverity } from "./validation";

describe("mobile validation", () => {
  it("validates quantities with decimal comma", () => {
    expect(validateQuantity("12,5")).toBeNull();
    expect(validateQuantity("0")).not.toBeNull();
    expect(validateQuantity("abc")).not.toBeNull();
  });

  it("enforces currency minor units", () => {
    expect(validateAmount("15000", "XAF")).toBeNull();
    expect(validateAmount("15000,5", "XAF")).toMatch(/entier/);
    expect(validateAmount("9,99", "EUR")).toBeNull();
    expect(validateAmount("1", "ZZZ")).toMatch(/Devise/);
  });

  it("validates severity and local dates", () => {
    expect(validateSeverity("")).toBeNull();
    expect(validateSeverity("3")).toBeNull();
    expect(validateSeverity("7")).not.toBeNull();
    expect(todayIso(new Date(2026, 10, 8, 23, 30))).toBe("2026-11-08");
  });
});
