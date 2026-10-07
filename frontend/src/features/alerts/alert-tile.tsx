import { formatTime } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import {
  boundLabel,
  excessLabel,
  METRIC_COLORS,
  METRIC_LABELS,
  peakLabel,
  sinceLabel,
  type Alert,
} from "./alerts-api";
import { MetricIcon } from "./metric-icon";

type Props = { alert: Alert; nowMs: number; size?: "sm" | "lg" };

/** An open alert: metric colour on the edge, the peak in large type, the bound and the excess. */
export function AlertTile({ alert, nowMs, size = "sm" }: Props) {
  const bound = boundLabel(alert);
  const excess = excessLabel(alert);
  const since = sinceLabel(nowMs - Date.parse(alert.opened_at));
  return (
    <li
      className={cn(
        "bg-card relative flex items-center gap-4 rounded-lg border p-3 pl-4",
        size === "lg" && "p-4 pl-5",
      )}
      style={{ boxShadow: `inset 4px 0 0 ${METRIC_COLORS[alert.metric]}` }}
    >
      <MetricIcon metric={alert.metric} className={size === "lg" ? "size-11" : "size-9"} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span className="font-medium">{METRIC_LABELS[alert.metric]}</span>
          <span className="text-muted-foreground truncate text-xs">{alert.device_id}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3">
          <span
            className={cn("font-semibold tabular-nums", size === "lg" ? "text-3xl" : "text-2xl")}
          >
            {peakLabel(alert)}
          </span>
          {bound ? (
            <span className="text-muted-foreground text-sm">
              {alert.direction === "high" ? "dépasse la borne de" : "sous la borne de"} {bound}
            </span>
          ) : (
            <span className="text-muted-foreground text-sm">
              {alert.metric === "intruder"
                ? "visage reconnu par la caméra"
                : "alerte signalée par l'ESP"}
            </span>
          )}
          {excess && (
            <span className="bg-destructive/10 text-destructive rounded-md px-1.5 py-0.5 text-xs font-medium tabular-nums">
              {excess}
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0 text-right text-xs">
        <span className="text-destructive flex items-center justify-end gap-1.5 font-medium">
          <span className="relative flex size-2">
            <span className="bg-destructive absolute inline-flex size-full animate-ping rounded-full opacity-75" />
            <span className="bg-destructive relative inline-flex size-2 rounded-full" />
          </span>
          Ouverte
        </span>
        <span className="text-muted-foreground mt-0.5 block tabular-nums">
          depuis {since} · à {formatTime(Date.parse(alert.opened_at))}
        </span>
      </div>
    </li>
  );
}
