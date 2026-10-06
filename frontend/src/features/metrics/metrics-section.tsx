import { useCallback, useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/use-auth";
import { GasChart, GasGauge, HumidityChart, TemperatureChart } from "./charts";
import { MetricTiles } from "./metric-tiles";
import {
  bucketFor,
  DEVICES_PATH,
  LATEST_PATH,
  type Device,
  type Range,
  type Reading,
} from "./metrics-api";
import { MetricsFilters, type View } from "./metrics-filters";
import { ReadingsTable } from "./readings-table";
import { useReadings } from "./use-readings";
import { useSensorStream } from "./use-sensor-stream";

export function MetricsSection() {
  const { authFetch } = useAuth();
  const [devices, setDevices] = useState<Device[]>([]);
  const [devicesStatus, setDevicesStatus] = useState<"loading" | "ready" | "error">("loading");
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("15m");
  const [live, setLive] = useState(true);
  const [view, setView] = useState<View>("charts");
  const [latestFromApi, setLatestFromApi] = useState<Reading | null>(null);

  useEffect(() => {
    let cancelled = false;
    authFetch<Device[]>(DEVICES_PATH)
      .then((list) => {
        if (cancelled) return;
        setDevices(list);
        setDevicesStatus("ready");
        setDeviceId((current) => current ?? list[0]?.device_id ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setDevices([]);
        setDevicesStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  // Tiles need the very last reading even when the range is bucketed.
  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    authFetch<Reading[]>(LATEST_PATH)
      .then((rows) => {
        if (!cancelled) setLatestFromApi(rows.find((r) => r.device_id === deviceId) ?? null);
      })
      .catch(() => {
        if (!cancelled) setLatestFromApi(null);
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, deviceId]);

  const readings = useReadings(deviceId, range);
  const { push } = readings;
  const onReading = useCallback((reading: Reading) => push(reading), [push]);
  useSensorStream(live && deviceId !== null, onReading);

  const bucketed = bucketFor(range) !== null;
  const latest = readings.latest ?? latestFromApi;
  const previous = readings.previous;
  const gasMax = Math.max(0, ...readings.points.map((p) => p.gas ?? 0));

  return (
    <section aria-labelledby="metrics-title" className="space-y-4">
      <h1 id="metrics-title" className="text-2xl font-semibold">
        Dashboard
      </h1>
      <MetricsFilters
        devices={devices}
        deviceId={deviceId}
        onDeviceChange={setDeviceId}
        range={range}
        onRangeChange={setRange}
        live={live}
        onLiveChange={setLive}
        view={view}
        onViewChange={setView}
      />
      <MetricTiles latest={latest} previous={previous} />
      {devicesStatus === "error" && (
        <p className="text-destructive">Impossible de charger la liste des appareils.</p>
      )}
      {devicesStatus === "ready" && deviceId === null && (
        <p className="text-muted-foreground">Aucun appareil n'a encore envoyé de mesure.</p>
      )}
      {deviceId !== null && readings.status === "loading" && (
        <Skeleton role="status" aria-label="Chargement des mesures" className="h-56 w-full" />
      )}
      {readings.status === "error" && (
        <p className="text-destructive">Impossible de charger les mesures.</p>
      )}
      {readings.status === "ready" && readings.points.length === 0 && (
        <p className="text-muted-foreground">
          Aucune mesure pour cet appareil sur la plage choisie.
        </p>
      )}
      {readings.status === "ready" && readings.points.length > 0 && view === "charts" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <TemperatureChart points={readings.points} />
          <HumidityChart points={readings.points} />
          <GasChart points={readings.points} />
          <GasGauge value={latest?.gas_level ?? null} max={gasMax} />
        </div>
      )}
      {readings.status === "ready" && readings.points.length > 0 && view === "table" && (
        <ReadingsTable points={readings.points} bucketed={bucketed} />
      )}
    </section>
  );
}
