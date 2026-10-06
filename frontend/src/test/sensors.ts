import type { Bucket, Reading } from "@/features/metrics/metrics-api";

export const DEVICE = "esp-interieur";
export const NOW_MS = Date.UTC(2026, 9, 6, 9, 0, 0);

export function makeReading(overrides: Partial<Reading> = {}): Reading {
  return {
    id: crypto.randomUUID(),
    device_id: DEVICE,
    recorded_at: "2026-10-06T09:00:00Z",
    temperature_c: 22.5,
    humidity_pct: 48,
    gas_level: 410,
    gas_alert: false,
    ...overrides,
  };
}

/** n readings, one per minute, ending at `endMs`. */
export function readingsFixture(n: number, endMs: number): Reading[] {
  return Array.from({ length: n }, (_, i) =>
    makeReading({
      recorded_at: new Date(endMs - (n - 1 - i) * 60_000).toISOString(),
      temperature_c: 20 + i * 0.5,
      humidity_pct: 40 + i,
      gas_level: 400 + i * 10,
    }),
  );
}

export function bucketsFixture(n: number, endMs: number, bucketMs: number): Bucket[] {
  return Array.from({ length: n }, (_, i) => ({
    bucket_start: new Date(endMs - (n - 1 - i) * bucketMs).toISOString(),
    count: 5,
    temperature_avg: 21 + i,
    temperature_min: 20 + i,
    temperature_max: 22 + i,
    humidity_avg: 50,
    humidity_min: 45,
    humidity_max: 55,
    gas_avg: 500 + i * 100,
    gas_min: 450,
    gas_max: 550 + i * 100,
    gas_alerts: i === n - 1 ? 1 : 0,
  }));
}
