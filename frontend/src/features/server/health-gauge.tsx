import { Area, AreaChart } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { cn } from "@/lib/utils";

type Props = {
  label: string;
  valueText: string;
  /** 0..1 fill of the bar, null when unknown. */
  ratio: number | null;
  warn: boolean;
  /** Last 30 min of the metric, oldest first; null points are skipped. */
  series: (number | null)[];
};

const sparkConfig = { v: { label: "", color: "var(--chart-3)" } } satisfies ChartConfig;
const sparkDimension = { width: 120, height: 28 };

/** A compact gauge: label, value, bar, sparkline. Colour is never the only signal. */
export function HealthGauge({ label, valueText, ratio, warn, series }: Props) {
  const pct = ratio === null ? null : Math.round(Math.min(1, Math.max(0, ratio)) * 100);
  const data = series.map((v, i) => ({ i, v }));
  const colour = warn ? "var(--destructive)" : "var(--chart-3)";
  return (
    <div role="group" aria-label={label} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-right text-sm font-semibold tabular-nums">{valueText}</p>
      <div
        role="progressbar"
        aria-label={`${label} : ${valueText}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? undefined}
        data-warn={warn ? "true" : "false"}
        className="bg-muted h-1.5 w-full self-center overflow-hidden rounded-full"
      >
        <div
          className={cn("h-full rounded-full", warn ? "bg-destructive" : "bg-[var(--chart-3)]")}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>
      <ChartContainer
        config={sparkConfig}
        className="h-7 w-[120px] [&_svg]:overflow-visible"
        initialDimension={sparkDimension}
      >
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <Area
            dataKey="v"
            type="monotone"
            stroke={colour}
            fill={colour}
            fillOpacity={0.15}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
}
