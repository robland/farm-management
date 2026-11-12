import { describe, expect, it } from "vitest";

import { currentPhase } from "./model";

describe("current phase", () => {
  const phases = [
    { phase_code: "nursery", sequence: 1, duration_days: 25, start_date: "2026-10-13", end_date: "2026-11-06" },
    { phase_code: "transplanting", sequence: 2, duration_days: 3, start_date: "2026-11-07", end_date: "2026-11-09" },
    { phase_code: "vegetative", sequence: 3, duration_days: null, start_date: null, end_date: null },
  ];

  it("finds the phase running on a day, bounds included", () => {
    expect(currentPhase(phases, "2026-11-09")?.phase_code).toBe("transplanting");
    expect(currentPhase(phases, "2026-11-06")?.phase_code).toBe("nursery");
  });

  it("returns nothing between or after dated phases", () => {
    expect(currentPhase(phases, "2026-12-01")).toBeUndefined();
  });
});
