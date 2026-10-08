import { describe, expect, it } from "vitest";
import { dayLabel, groupByDay } from "./day-groups";

const NOW = Date.UTC(2026, 9, 8, 9, 0, 0);

describe("day groups", () => {
  it("labels today, yesterday and older days", () => {
    expect(dayLabel(NOW - 60_000, NOW)).toBe("Aujourd'hui");
    expect(dayLabel(NOW - 86_400_000, NOW)).toBe("Hier");
    expect(dayLabel(Date.UTC(2026, 9, 5, 12), NOW)).toMatch(/^lun\. 5 oct\.$/);
  });

  it("groups any items by the day of the given timestamp, keeping their order", () => {
    const items = [
      { id: "a", at: new Date(NOW - 60_000).toISOString() },
      { id: "b", at: new Date(NOW - 120_000).toISOString() },
      { id: "c", at: new Date(NOW - 86_400_000).toISOString() },
    ];
    const groups = groupByDay(items, NOW, (i) => i.at);
    expect(groups.map((g) => g.label)).toEqual(["Aujourd'hui", "Hier"]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["a", "b"]);
  });
});
