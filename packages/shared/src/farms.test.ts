import { describe, expect, it } from "vitest";

import { farmPayload, initials, organizationGroups, validateFarm } from "./index";

describe("farm creation", () => {
  const valid = { name: "Ferme Est", code: "ferme-est", country: "cm", timezone: "Africa/Douala", currency: "XAF" };

  it("accepts a complete form and normalizes the payload", () => {
    expect(validateFarm(valid)).toEqual({});
    expect(farmPayload({ ...valid, name: " Ferme Est " })).toEqual({ ...valid, country: "CM" });
  });

  it("explains each invalid field", () => {
    expect(validateFarm({ name: " ", code: "", country: "CMR", timezone: "", currency: "" })).toEqual({
      name: "Nom obligatoire.", code: "Code obligatoire.", country: "Code pays à 2 lettres (ISO 3166), ex. CM.",
      timezone: "Fuseau horaire obligatoire.", currency: "Devise obligatoire.",
    });
    expect(validateFarm({ ...valid, code: "ferme é" }).code).toBe("Lettres sans accent, chiffres, - et _ uniquement.");
    expect(validateFarm({ ...valid, code: "x".repeat(33) }).code).toBe("32 caractères au maximum.");
  });
});

describe("farm picker", () => {
  it("groups farms by organization and lists administered organizations without farms", () => {
    const groups = organizationGroups({
      organizations: [{ id: "o1", name: "Coop", is_org_admin: false },
                      { id: "o2", name: "Asso", is_org_admin: true },
                      { id: "o3", name: "Autre", is_org_admin: false }],
      farms: [{ id: "f1", organization_id: "o1" }, { id: "f2", organization_id: "o1" }],
    });
    expect(groups.map((g) => [g.name, g.isAdmin, g.farms.map((f) => f.id)])).toEqual([
      ["Coop", false, ["f1", "f2"]],
      ["Asso", true, []],
    ]);
  });

  it("builds avatar initials", () => {
    expect(initials("Awa Diallo")).toBe("AD");
    expect(initials("  marie  claire  ngo ")).toBe("MN");
    expect(initials("Léon")).toBe("L");
    expect(initials("")).toBe("?");
  });
});
