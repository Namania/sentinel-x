import { describe, expect, it } from "vitest";
import { makeReading } from "@/test/sensors";
import { appendLive, bucketFor, readingsPath, toPoints } from "./metrics-api";

const NOW = Date.UTC(2026, 9, 6, 9, 0, 0);

describe("metrics api helpers", () => {
  it("picks the bucket from the range", () => {
    expect(bucketFor("15m")).toBeNull();
    expect(bucketFor("1h")).toBe("1m");
    expect(bucketFor("6h")).toBe("5m");
    expect(bucketFor("24h")).toBe("15m");
  });

  it("builds the history path with from and bucket", () => {
    expect(readingsPath("esp-interieur", "15m", NOW)).toBe(
      "/sensors/readings?device_id=esp-interieur&from=2026-10-06T08%3A45%3A00.000Z",
    );
    expect(readingsPath("esp-interieur", "6h", NOW)).toBe(
      "/sensors/readings?device_id=esp-interieur&from=2026-10-06T03%3A00%3A00.000Z&bucket=5m",
    );
  });

  it("maps raw readings and buckets to the same point shape", () => {
    const raw = toPoints([makeReading({ gas_level: 1600, gas_alert: true })], false);
    expect(raw[0]).toMatchObject({ temperature: 22.5, humidity: 48, gas: 1600, gasAlert: true });
    const bucketed = toPoints(
      [
        {
          bucket_start: "2026-10-06T09:00:00Z",
          count: 2,
          temperature_avg: 21,
          temperature_min: 20,
          temperature_max: 22,
          humidity_avg: 50,
          humidity_min: 45,
          humidity_max: 55,
          gas_avg: null,
          gas_min: null,
          gas_max: null,
          gas_alerts: 0,
        },
      ],
      true,
    );
    expect(bucketed[0]).toMatchObject({
      temperature: 21,
      humidity: 50,
      gas: null,
      gasAlert: false,
    });
  });

  it("keeps the bucket maximum so the gauge compares like with like", () => {
    const raw = toPoints([makeReading({ gas_level: 1600 })], false);
    expect(raw[0]!.gasMax).toBe(1600);
    const [point] = toPoints(
      [
        {
          bucket_start: "2026-10-06T09:00:00Z",
          count: 3,
          temperature_avg: 21,
          temperature_min: 20,
          temperature_max: 22,
          humidity_avg: 50,
          humidity_min: 45,
          humidity_max: 55,
          gas_avg: 500,
          gas_min: 400,
          gas_max: 900,
          gas_alerts: 0,
        },
      ],
      true,
    );
    expect(point!.gas).toBe(500);
    expect(point!.gasMax).toBe(900);
  });

  it("appends a live reading as a new raw point and drops points outside the range", () => {
    const old = {
      time: NOW - 16 * 60_000,
      temperature: 1,
      humidity: 1,
      gas: 1,
      gasMax: 1,
      gasAlert: false,
    };
    const points = appendLive(
      [old],
      makeReading({ recorded_at: new Date(NOW).toISOString() }),
      "15m",
      null,
    );
    expect(points).toHaveLength(1);
    expect(points[0]!.time).toBe(NOW);
  });

  it("folds a live reading into the current bucket when aggregated", () => {
    const current = {
      time: NOW - 30_000,
      temperature: 20,
      humidity: 40,
      gas: 400,
      gasMax: 400,
      gasAlert: false,
    };
    const points = appendLive(
      [current],
      makeReading({ recorded_at: new Date(NOW).toISOString(), gas_alert: true }),
      "1h",
      60_000,
    );
    expect(points).toHaveLength(1);
    expect(points[0]).toMatchObject({ time: NOW - 30_000, gasMax: 410, gasAlert: true });
    expect(points[0]!.temperature).toBeCloseTo(21.25);
    expect(points[0]!.gas).toBeCloseTo(405);
  });
});
