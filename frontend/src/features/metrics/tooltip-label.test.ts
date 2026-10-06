import { expect, it } from "vitest";
import { tooltipTimeLabel } from "./tooltip-label";

const t = Date.UTC(2026, 9, 6, 9, 5, 0); // 11:05 in Europe/Paris

it("reads the time of the hovered point from the payload", () => {
  // shadcn passes the series label as `value` when the axis value is a number
  expect(tooltipTimeLabel("Température (°C)", [{ payload: { time: t } }])).toBe("11:05");
});

it("falls back to a numeric axis value", () => {
  expect(tooltipTimeLabel(t, [])).toBe("11:05");
});

it("degrades to a dash instead of throwing", () => {
  expect(tooltipTimeLabel("Température (°C)", [])).toBe("–");
  expect(tooltipTimeLabel(undefined, undefined)).toBe("–");
});
