export type Reading = {
  id: string;
  device_id: string;
  recorded_at: string;
  temperature_c: number | null;
  humidity_pct: number | null;
  gas_level: number | null;
  gas_alert: boolean;
};

export type Bucket = {
  bucket_start: string;
  count: number;
  temperature_avg: number | null;
  temperature_min: number | null;
  temperature_max: number | null;
  humidity_avg: number | null;
  humidity_min: number | null;
  humidity_max: number | null;
  gas_avg: number | null;
  gas_min: number | null;
  gas_max: number | null;
  gas_alerts: number;
};

export type Device = { device_id: string; last_seen: string };

export type Range = "15m" | "1h" | "6h" | "24h";
export const RANGES: readonly Range[] = ["15m", "1h", "6h", "24h"];
export const RANGE_LABELS: Record<Range, string> = {
  "15m": "15 min",
  "1h": "1 h",
  "6h": "6 h",
  "24h": "24 h",
};
export const RANGE_MS: Record<Range, number> = {
  "15m": 15 * 60_000,
  "1h": 60 * 60_000,
  "6h": 6 * 60 * 60_000,
  "24h": 24 * 60 * 60_000,
};

export type BucketSize = "1m" | "5m" | "15m";
export const BUCKET_MS: Record<BucketSize, number> = {
  "1m": 60_000,
  "5m": 300_000,
  "15m": 900_000,
};

/** Raw readings for a short range, averaged buckets beyond. */
export function bucketFor(range: Range): BucketSize | null {
  const bucket: Record<Range, BucketSize | null> = {
    "15m": null,
    "1h": "1m",
    "6h": "5m",
    "24h": "15m",
  };
  return bucket[range];
}

export const DEVICES_PATH = "/sensors/devices";
export const LATEST_PATH = "/sensors/latest";

export function readingsPath(deviceId: string, range: Range, nowMs: number): string {
  const params = new URLSearchParams({
    device_id: deviceId,
    from: new Date(nowMs - RANGE_MS[range]).toISOString(),
  });
  const bucket = bucketFor(range);
  if (bucket) params.set("bucket", bucket);
  return `/sensors/readings?${params.toString()}`;
}

/** One chart point, whatever the source (raw reading or bucket average). */
export type MetricPoint = {
  time: number;
  temperature: number | null;
  humidity: number | null;
  gas: number | null;
  /** Highest gas level behind this point (the reading itself, or the bucket maximum). */
  gasMax: number | null;
  gasAlert: boolean;
};

export function readingToPoint(reading: Reading): MetricPoint {
  return {
    time: Date.parse(reading.recorded_at),
    temperature: reading.temperature_c,
    humidity: reading.humidity_pct,
    gas: reading.gas_level,
    gasMax: reading.gas_level,
    gasAlert: reading.gas_alert,
  };
}

export function toPoints(rows: Reading[] | Bucket[], bucketed: boolean): MetricPoint[] {
  if (!bucketed) return (rows as Reading[]).map(readingToPoint);
  return (rows as Bucket[]).map((b) => ({
    time: Date.parse(b.bucket_start),
    temperature: b.temperature_avg,
    humidity: b.humidity_avg,
    gas: b.gas_avg,
    gasMax: b.gas_max,
    gasAlert: b.gas_alerts > 0,
  }));
}

function mean(current: number | null, incoming: number | null): number | null {
  if (current === null) return incoming;
  if (incoming === null) return current;
  return (current + incoming) / 2;
}

/**
 * Add a live reading to the series: as a new point when raw, folded into the current bucket
 * when aggregated (running mean, alert sticky). Points older than the range are dropped.
 */
function maxOf(...values: (number | null)[]): number | null {
  const known = values.filter((v): v is number => v !== null);
  return known.length ? Math.max(...known) : null;
}

export function appendLive(
  points: MetricPoint[],
  reading: Reading,
  range: Range,
  bucketMs: number | null,
): MetricPoint[] {
  const point = readingToPoint(reading);
  const cutoff = point.time - RANGE_MS[range];
  const kept = points.filter((p) => p.time >= cutoff);
  const last = kept.at(-1);
  if (bucketMs !== null && last && point.time - last.time < bucketMs) {
    const merged: MetricPoint = {
      time: last.time,
      temperature: mean(last.temperature, point.temperature),
      humidity: mean(last.humidity, point.humidity),
      gas: mean(last.gas, point.gas),
      gasMax: maxOf(last.gasMax, point.gasMax),
      gasAlert: last.gasAlert || point.gasAlert,
    };
    return [...kept.slice(0, -1), merged];
  }
  return [...kept, point];
}
