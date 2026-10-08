import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAuth } from "@/features/auth/use-auth";
import { DEVICES_PATH, type Device } from "@/features/metrics/metrics-api";
import { useNow } from "@/lib/use-now";
import { AlertRow } from "./alert-row";
import { AlertTile } from "./alert-tile";
import { SirenBar } from "./siren-bar";
import {
  ALERTS_LIMIT,
  groupByDay,
  isOpen,
  METRIC_COLORS,
  METRIC_LABELS,
  summarize,
  type Metric,
} from "./alerts-api";
import { useAlerts } from "./use-alerts";

type StateFilter = "all" | "open" | "resolved";
const ALL = "__all__";
const METRICS: Metric[] = ["temperature", "humidity", "gas"];

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
      </CardContent>
    </Card>
  );
}

/** The /alertes page: a summary, filters, open alerts as tiles, the history as a day timeline. */
export function AlertsPageContent({ nowMs }: { nowMs?: number }) {
  const { authFetch } = useAuth();
  const { status, alerts } = useAlerts();
  const tick = useNow();
  const now = nowMs ?? tick;
  const [devices, setDevices] = useState<Device[]>([]);
  const [state, setState] = useState<StateFilter>("all");
  const [metric, setMetric] = useState<Metric | typeof ALL>(ALL);
  const [device, setDevice] = useState<string>(ALL);

  useEffect(() => {
    let cancelled = false;
    authFetch<Device[]>(DEVICES_PATH)
      .then((list) => {
        if (!cancelled) setDevices(list);
      })
      .catch(() => {
        if (!cancelled) setDevices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const filtered = alerts
    .filter((a) => metric === ALL || a.metric === metric)
    .filter((a) => device === ALL || a.device_id === device);
  const open = state === "resolved" ? [] : filtered.filter(isOpen);
  const resolved = state === "open" ? [] : filtered.filter((a) => !isOpen(a));
  const summary = summarize(alerts, now);

  return (
    <section aria-labelledby="alerts-title" className="space-y-5">
      <h1 id="alerts-title" className="text-2xl font-semibold">
        Alertes
      </h1>

      {status === "ready" && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat
            label="Ouvertes maintenant"
            value={String(summary.open)}
            hint={summary.open === 0 ? "Tout est dans les bornes" : undefined}
          />
          <Stat label="Dernières 24 h" value={String(summary.last24h)} hint="alertes déclenchées" />
          <Stat
            label="Métrique la plus fréquente"
            value={summary.topMetric ? METRIC_LABELS[summary.topMetric] : "–"}
            hint={`sur ${alerts.length} ${alerts.length > 1 ? "alertes" : "alerte"} chargées`}
          />
        </div>
      )}

      <SirenBar />

      <div className="flex flex-wrap items-center gap-4">
        <ToggleGroup
          type="single"
          value={state}
          onValueChange={(v) => v && setState(v as StateFilter)}
          aria-label="État"
          variant="outline"
        >
          <ToggleGroupItem value="all">Toutes</ToggleGroupItem>
          <ToggleGroupItem value="open">Ouvertes</ToggleGroupItem>
          <ToggleGroupItem value="resolved">Résolues</ToggleGroupItem>
        </ToggleGroup>
        <ToggleGroup
          type="single"
          value={metric}
          onValueChange={(v) => v && setMetric(v as Metric | typeof ALL)}
          aria-label="Métrique"
          variant="outline"
        >
          <ToggleGroupItem value={ALL}>Toutes les métriques</ToggleGroupItem>
          {METRICS.map((m) => (
            <ToggleGroupItem key={m} value={m} className="gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block size-2 rounded-full"
                style={{ background: METRIC_COLORS[m] }}
              />
              {METRIC_LABELS[m]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <div className="flex items-center gap-2">
          <Label htmlFor="alerts-device">Appareil</Label>
          <Select value={device} onValueChange={setDevice}>
            <SelectTrigger id="alerts-device" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tous</SelectItem>
              {devices.map((d) => (
                <SelectItem key={d.device_id} value={d.device_id}>
                  {d.device_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {status === "loading" && (
        <Skeleton role="status" aria-label="Chargement des alertes" className="h-40 w-full" />
      )}
      {status === "error" && <p className="text-destructive">Alertes indisponibles.</p>}
      {status === "ready" && open.length === 0 && resolved.length === 0 && (
        <p className="text-muted-foreground">Aucune alerte</p>
      )}
      {status === "ready" && alerts.length >= ALERTS_LIMIT && (
        <p className="text-muted-foreground text-sm">
          Seules les {ALERTS_LIMIT} alertes les plus récentes sont affichées.
        </p>
      )}

      {open.length > 0 && (
        <section aria-labelledby="open-alerts-title" className="space-y-2">
          <h2 id="open-alerts-title" className="text-sm font-medium">
            En cours
          </h2>
          <ul className="space-y-2">
            {open.map((a) => (
              <AlertTile key={a.id} alert={a} nowMs={now} size="lg" />
            ))}
          </ul>
        </section>
      )}

      {resolved.length > 0 && (
        <section aria-labelledby="history-title" className="space-y-4">
          <h2 id="history-title" className="text-sm font-medium">
            Historique
          </h2>
          {groupByDay(resolved, now).map((group) => (
            <div key={group.label} className="relative pl-5">
              <span
                aria-hidden="true"
                className="bg-border absolute top-2 bottom-2 left-1.5 w-px"
              />
              <h3 className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
                <span
                  aria-hidden="true"
                  className="bg-muted-foreground/60 absolute top-1.5 left-0 size-3 rounded-full ring-4 ring-[var(--background)]"
                />
                {group.label}
              </h3>
              <ul className="divide-y" aria-label={`Alertes résolues, ${group.label}`}>
                {group.alerts.map((a) => (
                  <AlertRow key={a.id} alert={a} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}
    </section>
  );
}
