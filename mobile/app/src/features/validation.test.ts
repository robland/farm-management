import { describe, expect, it } from "vitest";

import { todayIso, validateQuantity, validateSeverity } from "./validation";

// Amounts: validated by @fms/shared (amountError, validateTransaction) and tested there.
describe("mobile validation", () => {
  it("validates quantities with decimal comma", () => {
    expect(validateQuantity("12,5")).toBeNull();
    expect(validateQuantity("0")).not.toBeNull();
    expect(validateQuantity("abc")).not.toBeNull();
  });

  it("validates severity and local dates", () => {
    expect(validateSeverity("")).toBeNull();
    expect(validateSeverity("3")).toBeNull();
    expect(validateSeverity("7")).not.toBeNull();
    expect(todayIso(new Date(2026, 10, 8, 23, 30))).toBe("2026-11-08");
  });
});
