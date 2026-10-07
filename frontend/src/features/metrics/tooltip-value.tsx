import type { ComponentProps } from "react";
import type { ChartTooltipContent } from "@/components/ui/chart";
import { formatNumber } from "@/lib/format-number";

type Formatter = NonNullable<ComponentProps<typeof ChartTooltipContent>["formatter"]>;

type Options = { label: string; digits: number; unit?: string };

/**
 * Tooltip row for a single-series chart: colour dot, series label, value in French with a fixed
 * precision. shadcn's default prints `toLocaleString()` of the raw number (« 0.722 »).
 */
export function valueFormatter({ label, digits, unit }: Options): Formatter {
  return (value, _name, item) => {
    const number = typeof value === "number" ? value : Number(value);
    const colour = (item as { color?: string } | undefined)?.color;
    return (
      <>
        <span
          aria-hidden="true"
          className="inline-block size-2.5 shrink-0 rounded-[2px]"
          style={{ background: colour ?? "var(--muted-foreground)" }}
        />
        <span className="text-muted-foreground flex-1">{label}</span>
        <span className="text-foreground font-mono font-medium tabular-nums">
          {unit ? `${formatNumber(number, digits)} ${unit}` : formatNumber(number, digits)}
        </span>
      </>
    );
  };
}
