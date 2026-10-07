import type { ReactNode } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { tooltipTimeLabel } from "@/features/metrics/tooltip-label";
import { valueFormatter } from "@/features/metrics/tooltip-value";
import { formatNumber, formatTime } from "@/lib/format-number";
import { toServerPoints, type ServerHealth, type ServerPoint } from "./server-api";

const cpuConfig = { cpu: { label: "CPU (%)", color: "var(--chart-3)" } } satisfies ChartConfig;
const memConfig = {
  memGib: { label: "Mémoire utilisée (Gio)", color: "var(--chart-3)" },
} satisfies ChartConfig;
const tempConfig = {
  temp: { label: "Température (°C)", color: "var(--chart-3)" },
} satisfies ChartConfig;

const axisProps = { tickLine: false, axisLine: false, tickMargin: 8, minTickGap: 32 } as const;
// jsdom cannot measure the container; a fixed initial size keeps Recharts quiet in tests.
const initialDimension = { width: 600, height: 224 };

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">
          <h2>{title}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function TimeAxis() {
  return <XAxis dataKey="time" tickFormatter={(v) => formatTime(Number(v))} {...axisProps} />;
}

export function CpuChart({ points }: { points: ServerPoint[] }) {
  return (
    <ChartCard title="CPU (%)">
      <ChartContainer
        config={cpuConfig}
        className="h-56 w-full"
        initialDimension={initialDimension}
      >
        <AreaChart data={points}>
          <CartesianGrid vertical={false} />
          <TimeAxis />
          <YAxis domain={[0, 100]} width={36} {...axisProps} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={tooltipTimeLabel}
                formatter={valueFormatter({ label: "CPU", digits: 0, unit: "%" })}
              />
            }
          />
          <Area
            dataKey="cpu"
            type="monotone"
            stroke="var(--color-cpu)"
            fill="var(--color-cpu)"
            fillOpacity={0.15}
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function MemoryChart({ points, totalGib }: { points: ServerPoint[]; totalGib: number }) {
  return (
    <ChartCard title="Mémoire utilisée (Gio)">
      <ChartContainer
        config={memConfig}
        className="h-56 w-full"
        initialDimension={initialDimension}
      >
        <AreaChart data={points}>
          <CartesianGrid vertical={false} />
          <TimeAxis />
          <YAxis
            domain={[0, Math.ceil(totalGib)]}
            width={36}
            tickFormatter={(v) => formatNumber(Number(v), 0)}
            {...axisProps}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={tooltipTimeLabel}
                formatter={valueFormatter({ label: "Mémoire utilisée", digits: 1, unit: "Gio" })}
              />
            }
          />
          <Area
            dataKey="memGib"
            type="monotone"
            stroke="var(--color-memGib)"
            fill="var(--color-memGib)"
            fillOpacity={0.15}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function ServerTemperatureChart({ points }: { points: ServerPoint[] }) {
  if (points.length > 0 && points.every((p) => p.temp === null)) {
    return (
      <ChartCard title="Température (°C)">
        <p className="text-muted-foreground grid h-56 place-items-center text-sm">
          Aucune sonde thermique exposée par l'hôte (normal sous Docker Desktop).
        </p>
      </ChartCard>
    );
  }
  return (
    <ChartCard title="Température (°C)">
      <ChartContainer
        config={tempConfig}
        className="h-56 w-full"
        initialDimension={initialDimension}
      >
        <LineChart data={points}>
          <CartesianGrid vertical={false} />
          <TimeAxis />
          <YAxis
            domain={["dataMin - 2", "dataMax + 2"]}
            width={36}
            tickFormatter={(v) => formatNumber(Number(v), 0)}
            {...axisProps}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={tooltipTimeLabel}
                formatter={valueFormatter({ label: "Température", digits: 1, unit: "°C" })}
              />
            }
          />
          <Line
            dataKey="temp"
            type="monotone"
            stroke="var(--color-temp)"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function ServerCharts({ history }: { history: ServerHealth[] }) {
  const points = toServerPoints(history);
  const totalGib = (history.at(-1)?.mem_total_bytes ?? 0) / 2 ** 30;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <CpuChart points={points} />
      <MemoryChart points={points} totalGib={totalGib} />
      <ServerTemperatureChart points={points} />
    </div>
  );
}
