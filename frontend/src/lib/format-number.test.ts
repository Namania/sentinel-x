import { expect, it } from "vitest";
import { formatDelta, formatNumber, formatTime } from "./format-number";

it("formats numbers in French with fixed digits", () => {
  expect(formatNumber(22.456, 1)).toBe("22,5");
  expect(formatNumber(1500, 0)).toBe("1\u202f500"); // fr-FR narrow no-break space
  expect(formatNumber(null, 1)).toBe("–");
});

it("formats a delta with its sign", () => {
  expect(formatDelta(22.5, 21.9, 1)).toBe("+0,6");
  expect(formatDelta(21.9, 22.5, 1)).toBe("−0,6");
  expect(formatDelta(22.5, null, 1)).toBeNull();
});

it("shows a variation that rounds to zero without a sign", () => {
  expect(formatDelta(43.2, 43.4, 0)).toBe("0");
  expect(formatDelta(22.51, 22.49, 1)).toBe("0,0");
});

it("formats a time of day", () => {
  expect(formatTime(Date.UTC(2026, 9, 6, 9, 5, 0))).toBe("11:05"); // tests run in Europe/Paris
});

it("never throws on an invalid time", () => {
  expect(formatTime(Number.NaN)).toBe("–");
  expect(formatTime(Number("Température (°C)"))).toBe("–");
});
