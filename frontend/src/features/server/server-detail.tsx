import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthGauge } from "./health-gauge";
import { formatBytesPair, formatUptime, loadLabel, ratio, USAGE_WARN_PCT } from "./server-api";
import { ServerCharts } from "./server-charts";
import { useServerHealth } from "./use-server-health";

/** The `/serveur` page body: the server card's series, full size, over the last 30 minutes. */
export function ServerDetail() {
  const { status, latest, history } = useServerHealth();
  const disk = latest ? ratio(latest.disk_used_bytes, latest.disk_total_bytes) : null;
  return (
    <section aria-labelledby="server-title" className="space-y-4">
      <h1 id="server-title" className="text-2xl font-semibold">
        Serveur
      </h1>
      {status === "loading" && (
        <Skeleton
          role="status"
          aria-label="Chargement de la santé du serveur"
          className="h-56 w-full"
        />
      )}
      {status === "error" && <p className="text-destructive">Santé du serveur indisponible.</p>}
      {status === "ready" && !latest && (
        <p className="text-muted-foreground">En attente du premier échantillon…</p>
      )}
      {latest && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Stockage</CardTitle>
              </CardHeader>
              <CardContent>
                <HealthGauge
                  label="Disque"
                  valueText={formatBytesPair(latest.disk_used_bytes, latest.disk_total_bytes)}
                  ratio={disk}
                  warn={(disk ?? 0) >= USAGE_WARN_PCT / 100}
                  series={history.map((h) => ratio(h.disk_used_bytes, h.disk_total_bytes))}
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Charge et disponibilité</CardTitle>
              </CardHeader>
              <CardContent className="text-sm tabular-nums">
                <p>{loadLabel(latest)}</p>
                <p className="text-muted-foreground">
                  Démarré depuis {formatUptime(latest.uptime_s)}
                </p>
              </CardContent>
            </Card>
          </div>
          <ServerCharts history={history} />
        </>
      )}
    </section>
  );
}
