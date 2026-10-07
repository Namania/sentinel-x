import { Bell, BellOff, BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { sirenLabel } from "./siren-api";
import { useSiren } from "./use-siren";

/** The ESP32 buzzer, as the API drives it: what it does now, and the button to mute or re-arm it. */
export function SirenBar({ className }: { className?: string }) {
  const { status, state, pending, error, mute, unmute } = useSiren();
  const muted = Boolean(state?.muted_until);
  const on = Boolean(state?.on);
  const Icon = on ? BellRing : muted ? BellOff : Bell;
  return (
    <div
      role="status"
      aria-label="Sirène"
      className={cn(
        "flex items-center gap-3 rounded-lg border px-3 py-2 text-sm",
        on && "border-destructive/40 bg-destructive/5",
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "size-4 shrink-0",
          on ? "text-destructive animate-pulse" : "text-muted-foreground",
        )}
      />
      <span className={cn("flex-1", !on && "text-muted-foreground")}>
        {status === "loading" && "Sirène…"}
        {status === "error" && "Sirène : état inconnu"}
        {status === "ready" && state && sirenLabel(state)}
        {error && <span className="text-destructive ml-2 text-xs">{error}</span>}
      </span>
      {status === "ready" && on && (
        <Button size="sm" variant="outline" disabled={pending} onClick={() => void mute()}>
          Couper 15 min
        </Button>
      )}
      {status === "ready" && muted && (
        <Button size="sm" variant="outline" disabled={pending} onClick={() => void unmute()}>
          Réactiver
        </Button>
      )}
    </div>
  );
}
