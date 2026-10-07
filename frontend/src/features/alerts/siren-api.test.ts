import { describe, expect, it } from "vitest";
import { makeSiren } from "@/test/siren";
import { sirenLabel } from "./siren-api";

describe("sirenLabel", () => {
  it("names the three states", () => {
    expect(sirenLabel(makeSiren())).toBe("Sirène au repos");
    expect(sirenLabel(makeSiren({ on: true, reason: "gas", open: 1 }))).toBe("Sirène active : gaz");
    expect(sirenLabel(makeSiren({ on: true, reason: "temperature", open: 1 }))).toBe(
      "Sirène active : température",
    );
    expect(
      sirenLabel(makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" })),
    ).toBe("Sirène coupée jusqu'à 09:27");
  });
});
