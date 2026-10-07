import { Droplets, Thermometer, Wind, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { METRIC_COLORS, type Metric } from "./alerts-api";

const ICONS: Record<Metric, LucideIcon> = {
  temperature: Thermometer,
  humidity: Droplets,
  gas: Wind,
};

/** The metric's pictogram in its colour, on a soft disc; decorative (the label says the metric). */
export function MetricIcon({ metric, className }: { metric: Metric; className?: string }) {
  const Icon = ICONS[metric];
  return (
    <span
      aria-hidden="true"
      className={cn("grid shrink-0 place-items-center rounded-full", className ?? "size-8")}
      style={{ background: `color-mix(in oklab, ${METRIC_COLORS[metric]} 18%, transparent)` }}
    >
      <Icon className="size-[55%]" style={{ color: METRIC_COLORS[metric] }} />
    </span>
  );
}
