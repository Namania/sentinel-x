import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";
import { AlertRow } from "./alert-row";
import { isOpen, RESOLVED_SHOWN, type Alert } from "./alerts-api";

type Props = {
  status: "loading" | "ready" | "error";
  alerts: Alert[];
  /** Injected by tests so « depuis 4 min » is deterministic; defaults to a 30 s clock. */
  nowMs?: number;
  className?: string;
};

/** Wall-screen card: open alerts first, the last few resolved ones, the whole card opens /alertes. */
export function AlertsCard({ status, alerts, nowMs, className }: Props) {
  const tick = useNow();
  const now = nowMs ?? tick;
  const open = alerts.filter(isOpen);
  const resolved = alerts.filter((a) => !isOpen(a)).slice(0, RESOLVED_SHOWN);
  return (
    <Link
      to="/alertes"
      aria-label="Alertes, voir l'historique"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium">Alertes</CardTitle>
          {status === "ready" &&
            (open.length > 0 ? (
              <Badge variant="destructive">
                {open.length} {open.length > 1 ? "ouvertes" : "ouverte"}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-muted-foreground">
                Aucune alerte
              </Badge>
            ))}
        </CardHeader>
        <CardContent>
          {status === "loading" && (
            <Skeleton role="status" aria-label="Chargement des alertes" className="h-16 w-full" />
          )}
          {status === "error" && <p className="text-destructive text-sm">Alertes indisponibles</p>}
          {status === "ready" && (open.length > 0 || resolved.length > 0) && (
            <ul className="divide-y">
              {[...open, ...resolved].map((a) => (
                <AlertRow key={a.id} alert={a} nowMs={now} />
              ))}
            </ul>
          )}
          {status === "ready" && open.length === 0 && resolved.length === 0 && (
            <p className="text-muted-foreground text-sm">Aucune alerte enregistrée.</p>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
