import { Check, X } from "lucide-react";
import { formatTime } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import { describeEvent, type SshEvent } from "./ssh-api";

/** One connection on one line: outcome mark, who/where/how, system user, time. */
export function SshEventRow({ event }: { event: SshEvent }) {
  const ok = event.outcome === "accepted";
  return (
    <li className="flex items-center gap-3 py-2 text-sm">
      <span
        aria-hidden="true"
        className={cn(
          "grid size-7 shrink-0 place-items-center rounded-full",
          ok
            ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            : "bg-destructive/15 text-destructive",
        )}
      >
        {ok ? <Check className="size-4" /> : <X className="size-4" />}
      </span>
      <span className="min-w-0 flex-1 truncate">{describeEvent(event)}</span>
      <span
        className="text-muted-foreground hidden w-24 shrink-0 truncate text-xs sm:inline"
        title={`port ${event.port}`}
      >
        {event.username}
      </span>
      <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
        {formatTime(Date.parse(event.occurred_at))}
      </span>
      <span className="sr-only">{ok ? "Acceptée" : "Refusée"}</span>
    </li>
  );
}
