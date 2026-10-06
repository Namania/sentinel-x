import { formatTime } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import { describeAlert, durationLabel, isOpen, type Alert } from "./alerts-api";

/** One alert, as a list item: state word + dot, device, description, when, how long. */
export function AlertRow({ alert, nowMs }: { alert: Alert; nowMs: number }) {
  const open = isOpen(alert);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm">
      <span className="flex w-20 shrink-0 items-center gap-1.5">
        <span
          aria-hidden="true"
          className={cn(
            "inline-block size-2 rounded-full",
            open ? "bg-destructive" : "bg-muted-foreground/60",
          )}
        />
        <span
          className={cn("text-xs font-medium", open ? "text-destructive" : "text-muted-foreground")}
        >
          {open ? "Ouverte" : "Résolue"}
        </span>
      </span>
      <span className="text-muted-foreground w-28 shrink-0 truncate text-xs">
        {alert.device_id}
      </span>
      <span className={cn("flex-1 tabular-nums", !open && "text-muted-foreground")}>
        {describeAlert(alert)}
      </span>
      <span className="text-muted-foreground text-xs tabular-nums">
        à {formatTime(Date.parse(alert.opened_at))} · {durationLabel(alert, nowMs)}
      </span>
    </li>
  );
}
