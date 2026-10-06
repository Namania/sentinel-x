import { useEffect, useState } from "react";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAuth } from "@/features/auth/use-auth";
import { DEVICES_PATH, type Device } from "@/features/metrics/metrics-api";
import { formatTime } from "@/lib/format-number";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";
import { durationLabel, isOpen, METRIC_LABELS, valueAgainstBound } from "./alerts-api";
import { useAlerts } from "./use-alerts";

type StateFilter = "all" | "open" | "resolved";
const ALL_DEVICES = "__all__";

/** The /alertes page: filters by state and device, full history in a table. */
export function AlertsPageContent({ nowMs }: { nowMs?: number }) {
  const { authFetch } = useAuth();
  const { status, alerts } = useAlerts();
  const tick = useNow();
  const now = nowMs ?? tick;
  const [devices, setDevices] = useState<Device[]>([]);
  const [state, setState] = useState<StateFilter>("all");
  const [device, setDevice] = useState<string>(ALL_DEVICES);

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

  const rows = alerts
    .filter((a) => state === "all" || (state === "open") === isOpen(a))
    .filter((a) => device === ALL_DEVICES || a.device_id === device);

  return (
    <section aria-labelledby="alerts-title" className="space-y-4">
      <h1 id="alerts-title" className="text-2xl font-semibold">
        Alertes
      </h1>
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
        <div className="flex items-center gap-2">
          <Label htmlFor="alerts-device">Appareil</Label>
          <Select value={device} onValueChange={setDevice}>
            <SelectTrigger id="alerts-device" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_DEVICES}>Tous</SelectItem>
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
      {status === "ready" && rows.length === 0 && (
        <p className="text-muted-foreground">Aucune alerte</p>
      )}
      {status === "ready" && rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>État</TableHead>
              <TableHead>Appareil</TableHead>
              <TableHead>Métrique</TableHead>
              <TableHead>Valeur / borne</TableHead>
              <TableHead>Ouverte à</TableHead>
              <TableHead>Résolue à</TableHead>
              <TableHead>Durée</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((a) => {
              const open = isOpen(a);
              return (
                <TableRow key={a.id}>
                  <TableCell>
                    <span
                      className={cn(
                        "flex items-center gap-1.5 text-xs font-medium",
                        open ? "text-destructive" : "text-muted-foreground",
                      )}
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "inline-block size-2 rounded-full",
                          open ? "bg-destructive" : "bg-muted-foreground/60",
                        )}
                      />
                      {open ? "Ouverte" : "Résolue"}
                    </span>
                  </TableCell>
                  <TableCell>{a.device_id}</TableCell>
                  <TableCell>{METRIC_LABELS[a.metric]}</TableCell>
                  <TableCell className="tabular-nums">{valueAgainstBound(a)}</TableCell>
                  <TableCell className="tabular-nums">
                    {formatTime(Date.parse(a.opened_at))}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {a.resolved_at ? formatTime(Date.parse(a.resolved_at)) : "–"}
                  </TableCell>
                  <TableCell className="tabular-nums">{durationLabel(a, now)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
