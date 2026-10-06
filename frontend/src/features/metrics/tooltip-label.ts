import { formatTime } from "@/lib/format-number";

type PayloadItem = { payload?: { time?: unknown } };

/**
 * Label of a chart tooltip: the time of the hovered point. shadcn's ChartTooltipContent passes
 * the series label (a string) as `value` when the axis value is a number, so the time is read
 * from the hovered point's data first; a numeric `value` is accepted as a fallback.
 */
export function tooltipTimeLabel(value: unknown, payload?: ReadonlyArray<PayloadItem>): string {
  const fromPoint = payload?.[0]?.payload?.time;
  if (typeof fromPoint === "number") return formatTime(fromPoint);
  if (typeof value === "number") return formatTime(value);
  return "–";
}
