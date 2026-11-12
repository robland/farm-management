import { describe, expect, it } from "vitest";

import { hasErrors, validateParcel } from "./validation";

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
