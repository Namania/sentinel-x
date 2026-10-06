import { Link } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { HealthGauge } from "./health-gauge";
import {
  formatBytesPair,
  formatPct,
  formatTemperature,
  formatUptime,
  loadLabel,
  ratio,
  TEMPERATURE_WARN_C,
  USAGE_WARN_PCT,
  type ServerHealth,
} from "./server-api";
import { useServerHealth } from "./use-server-health";

const WARN_RATIO = USAGE_WARN_PCT / 100;

function Gauges({ latest, history }: { latest: ServerHealth; history: ServerHealth[] }) {
  const mem = ratio(latest.mem_used_bytes, latest.mem_total_bytes);
  const disk = ratio(latest.disk_used_bytes, latest.disk_total_bytes);
  const cpu = latest.cpu_pct === null ? null : latest.cpu_pct / 100;
  return (
    <>
      <HealthGauge
        label="CPU"
        valueText={formatPct(latest.cpu_pct)}
        ratio={cpu}
        warn={(latest.cpu_pct ?? 0) >= USAGE_WARN_PCT}
        series={history.map((h) => h.cpu_pct)}
      />
      <HealthGauge
        label="Mémoire"
        valueText={formatBytesPair(latest.mem_used_bytes, latest.mem_total_bytes)}
        ratio={mem}
        warn={(mem ?? 0) >= WARN_RATIO}
        series={history.map((h) => ratio(h.mem_used_bytes, h.mem_total_bytes))}
      />
      <HealthGauge
        label="Disque"
        valueText={formatBytesPair(latest.disk_used_bytes, latest.disk_total_bytes)}
        ratio={disk}
        warn={(disk ?? 0) >= WARN_RATIO}
        series={history.map((h) => ratio(h.disk_used_bytes, h.disk_total_bytes))}
      />
      <HealthGauge
        label="Température"
        valueText={formatTemperature(latest.temperature_c)}
        ratio={latest.temperature_c === null ? null : latest.temperature_c / 100}
        warn={(latest.temperature_c ?? 0) >= TEMPERATURE_WARN_C}
        series={history.map((h) => h.temperature_c)}
      />
    </>
  );
}

/** Wall-screen card: the host's health at a glance; the whole card opens the detail page. */
export function ServerHealthCard({ className }: { className?: string }) {
  const { status, latest, history, connected } = useServerHealth();
  return (
    <Link
      to="/serveur"
      aria-label="Santé du serveur, voir le détail"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium">Serveur</CardTitle>
          <span className="flex items-center gap-1.5 text-xs">
            <span
              className={cn(
                "inline-block size-2 rounded-full",
                connected ? "bg-emerald-500" : "bg-muted-foreground/50",
              )}
              aria-hidden="true"
            />
            <span className="sr-only">
              {connected ? "temps réel actif" : "temps réel interrompu"}
            </span>
          </span>
        </CardHeader>
        <CardContent className="space-y-3">
          {status === "loading" && (
            <Skeleton
              role="status"
              aria-label="Chargement de la santé du serveur"
              className="h-40 w-full"
            />
          )}
          {status === "error" && (
            <p className="text-destructive text-sm">Santé du serveur indisponible</p>
          )}
          {status === "ready" && latest && <Gauges latest={latest} history={history} />}
          {status === "ready" && !latest && (
            <p className="text-muted-foreground text-sm">En attente du premier échantillon…</p>
          )}
          {latest && (
            <div className="text-muted-foreground text-xs tabular-nums">
              <p>{loadLabel(latest)}</p>
              <p>Démarré depuis {formatUptime(latest.uptime_s)}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
