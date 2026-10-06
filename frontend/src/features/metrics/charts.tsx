import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { formatNumber, formatTime } from "@/lib/format-number";
import type { MetricPoint } from "./metrics-api";
import { tooltipTimeLabel } from "./tooltip-label";

const temperatureConfig = {
  temperature: { label: "Température (°C)", color: "var(--metric-temperature)" },
} satisfies ChartConfig;
const humidityConfig = {
  humidity: { label: "Humidité (%)", color: "var(--metric-humidity)" },
} satisfies ChartConfig;
const gasConfig = { gas: { label: "Gaz (ppm)", color: "var(--metric-gas)" } } satisfies ChartConfig;

const axisProps = { tickLine: false, axisLine: false, tickMargin: 8, minTickGap: 32 } as const;
// jsdom cannot measure the container; a fixed initial size keeps Recharts quiet in tests.
const initialDimension = { width: 600, height: 224 };

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

type MarkerProps = {
  x?: number | string;
  y?: number | string;
  width?: number | string;
  value?: unknown;
};

/** A small triangle above a bar whose bucket contains a gas alert: identity never by colour alone. */
function AlertMarker({ x, y, width, value }: MarkerProps) {
  if (!value || x === undefined || y === undefined || width === undefined) return null;
  const cx = Number(x) + Number(width) / 2;
  const top = Number(y) - 10;
  return (
    <g role="img" aria-label="Alerte gaz">
      <polygon
        points={`${cx},${top - 6} ${cx - 5},${top + 2} ${cx + 5},${top + 2}`}
        fill="var(--destructive)"
      />
    </g>
  );
}

export function TemperatureChart({ points }: { points: MetricPoint[] }) {
  return (
    <ChartCard title="Température (°C)">
      <ChartContainer
        config={temperatureConfig}
        className="h-56 w-full"
        initialDimension={initialDimension}
      >
        <LineChart data={points} margin={{ left: 0, right: 12 }}>
          <CartesianGrid vertical={false} strokeOpacity={0.4} />
          <XAxis
            dataKey="time"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatTime}
            {...axisProps}
          />
          <YAxis
            width={40}
            domain={["dataMin - 1", "dataMax + 1"]}
            tickFormatter={(v) => formatNumber(Number(v), 0)}
            {...axisProps}
          />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipTimeLabel} />} />
          <Line
            dataKey="temperature"
            type="monotone"
            stroke="var(--color-temperature)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5 }}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function HumidityChart({ points }: { points: MetricPoint[] }) {
  return (
    <ChartCard title="Humidité (%)">
      <ChartContainer
        config={humidityConfig}
        className="h-56 w-full"
        initialDimension={initialDimension}
      >
        <AreaChart data={points} margin={{ left: 0, right: 12 }}>
          <CartesianGrid vertical={false} strokeOpacity={0.4} />
          <XAxis
            dataKey="time"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatTime}
            {...axisProps}
          />
          <YAxis width={40} domain={[0, 100]} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipTimeLabel} />} />
          <Area
            dataKey="humidity"
            type="monotone"
            stroke="var(--color-humidity)"
            fill="var(--color-humidity)"
            fillOpacity={0.2}
            strokeWidth={2}
            connectNulls
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function GasChart({ points }: { points: MetricPoint[] }) {
  return (
    <ChartCard title="Gaz (ppm, moyenne par intervalle)">
      <ChartContainer
        config={gasConfig}
        className="h-56 w-full"
        initialDimension={initialDimension}
      >
        <BarChart data={points} margin={{ left: 0, right: 12 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} strokeOpacity={0.4} />
          <XAxis dataKey="time" tickFormatter={formatTime} {...axisProps} />
          <YAxis width={48} tickFormatter={(v) => formatNumber(Number(v), 0)} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipTimeLabel} />} />
          {/* No animations: live data redraws every few seconds, and bar labels only appear once it ends. */}
          <Bar
            dataKey="gas"
            fill="var(--color-gas)"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          >
            {points.map((p) => (
              <Cell key={p.time} fill={p.gasAlert ? "var(--destructive)" : "var(--color-gas)"} />
            ))}
            <LabelList
              valueAccessor={(entry: { payload?: MetricPoint }) =>
                entry.payload?.gasAlert ? 1 : null
              }
              content={<AlertMarker />}
            />
          </Bar>
        </BarChart>
      </ChartContainer>
      <p className="text-muted-foreground mt-2 text-xs">
        Un triangle rouge au-dessus d'une barre signale une alerte gaz dans l'intervalle.
      </p>
    </ChartCard>
  );
}

export function GasGauge({ value, max }: { value: number | null; max: number }) {
  const ratio = value === null ? 0 : Math.min(1, value / Math.max(max, 1));
  const data = [{ name: "gas", value: ratio * 100 }];
  return (
    <ChartCard title="Gaz : dernière valeur vs maximum de la plage">
      <ChartContainer
        config={gasConfig}
        className="mx-auto aspect-square h-56"
        initialDimension={{ width: 224, height: 224 }}
      >
        <RadialBarChart
          data={data}
          innerRadius="70%"
          outerRadius="100%"
          startAngle={210}
          endAngle={-30}
        >
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar dataKey="value" background cornerRadius={4} fill="var(--color-gas)" />
        </RadialBarChart>
      </ChartContainer>
      <p className="text-center text-2xl font-semibold tabular-nums">
        {formatNumber(value, 0)}{" "}
        <span className="text-muted-foreground text-sm font-normal">
          / {formatNumber(max, 0)} ppm
        </span>
      </p>
    </ChartCard>
  );
}
