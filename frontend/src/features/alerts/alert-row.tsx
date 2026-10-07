import { formatDuration, formatTime } from "@/lib/format-number";
import { describeAlert, timeRange, type Alert } from "./alerts-api";
import { MetricIcon } from "./metric-icon";

/** A resolved alert, one compact line: icon, what happened, where, when and for how long. */
export function AlertRow({ alert }: { alert: Alert }) {
  const duration = alert.resolved_at
    ? formatDuration(Date.parse(alert.resolved_at) - Date.parse(alert.opened_at))
    : null;
  return (
    <li className="flex items-center gap-3 py-2 text-sm">
      <MetricIcon metric={alert.metric} className="size-7" />
      <span className="min-w-0 flex-1 truncate">
        <span className="text-muted-foreground">{describeAlert(alert)}</span>
      </span>
      <span className="text-muted-foreground hidden w-28 shrink-0 truncate text-xs sm:inline">
        {alert.device_id}
      </span>
      <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
        {timeRange(alert, formatTime)}
        {duration ? ` · ${duration}` : ""}
      </span>
      <span className="sr-only">Résolue</span>
    </li>
  );
}
