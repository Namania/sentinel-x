import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatTime } from "@/lib/format-number";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";
import { AlertRow } from "./alert-row";
import { AlertTile } from "./alert-tile";
import { dayLabel, isOpen, RESOLVED_SHOWN, type Alert } from "./alerts-api";

type Props = {
  status: "loading" | "ready" | "error";
  alerts: Alert[];
  /** Injected by tests so « depuis 4 min » is deterministic; defaults to a 30 s clock. */
  nowMs?: number;
  className?: string;
};

/** Wall-screen card: open alerts as tiles, the last resolved ones as a quiet list; one link. */
export function AlertsCard({ status, alerts, nowMs, className }: Props) {
  const tick = useNow();
  const now = nowMs ?? tick;
  const open = alerts.filter(isOpen);
  const resolved = alerts.filter((a) => !isOpen(a));
  const resolvedToday = resolved.filter(
    (a) => dayLabel(Date.parse(a.resolved_at!), now) === "Aujourd'hui",
  ).length;
  const lastResolved = resolved[0];
  return (
    <Link
      to="/alertes"
      aria-label="Alertes, voir l'historique"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium">Alertes</CardTitle>
          {status === "ready" && (
            <span className="flex items-center gap-2 text-xs">
              {open.length > 0 ? (
                <Badge variant="destructive">
                  {open.length} {open.length > 1 ? "ouvertes" : "ouverte"}
                </Badge>
              ) : (
                <Badge variant="outline" className="text-muted-foreground">
                  Aucune ouverte
                </Badge>
              )}
              <span className="text-muted-foreground tabular-nums">
                {resolvedToday} {resolvedToday > 1 ? "résolues" : "résolue"} aujourd'hui
              </span>
            </span>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {status === "loading" && (
            <Skeleton role="status" aria-label="Chargement des alertes" className="h-16 w-full" />
          )}
          {status === "error" && <p className="text-destructive text-sm">Alertes indisponibles</p>}
          {status === "ready" && open.length > 0 && (
            <ul className="space-y-2" aria-label="Alertes ouvertes">
              {open.map((a) => (
                <AlertTile key={a.id} alert={a} nowMs={now} />
              ))}
            </ul>
          )}
          {status === "ready" && open.length === 0 && (
            <p className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="size-4 text-emerald-500" aria-hidden="true" />
              Tout est dans les bornes
              {lastResolved?.resolved_at && (
                <span className="text-muted-foreground">
                  · dernière alerte résolue à {formatTime(Date.parse(lastResolved.resolved_at))}
                </span>
              )}
            </p>
          )}
          {status === "ready" && resolved.length > 0 && (
            <div>
              <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
                Dernières résolues
              </p>
              <ul className="divide-y" aria-label="Dernières alertes résolues">
                {resolved.slice(0, RESOLVED_SHOWN).map((a) => (
                  <AlertRow key={a.id} alert={a} />
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
