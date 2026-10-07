import { describe, expect, it } from "vitest";
import { formatNumber } from "@/lib/format-number";
import { ALERTS_NOW_MS, makeAlert } from "@/test/alerts";
import {
  boundLabel,
  dayLabel,
  describeAlert,
  durationLabel,
  excessLabel,
  formatDuration,
  groupByDay,
  peakLabel,
  sortAlerts,
  summarize,
  upsert,
} from "./alerts-api";

describe("alerts api helpers", () => {
  it("describes an alert with its peak and its bound", () => {
    expect(describeAlert(makeAlert())).toBe("Température 31,2 °C > 30 °C");
    expect(
      describeAlert(
        makeAlert({ metric: "humidity", direction: "low", threshold: 20, peak_value: 12 }),
      ),
    ).toBe("Humidité 12 % < 20 %");
    expect(describeAlert(makeAlert({ metric: "gas", threshold: 1500, peak_value: 1800 }))).toBe(
      `Gaz ${formatNumber(1800, 0)} mV > ${formatNumber(1500, 0)} mV`,
    );
    expect(describeAlert(makeAlert({ metric: "gas", threshold: 0, peak_value: 1800 }))).toBe(
      `Gaz : alerte ESP (${formatNumber(1800, 0)} mV)`,
    );
    expect(describeAlert(makeAlert({ metric: "gas", threshold: 0, peak_value: 0 }))).toBe(
      "Gaz : alerte ESP",
    );
  });

  it("formats durations in French", () => {
    expect(formatDuration(30_000)).toBe("30 s");
    expect(formatDuration(4 * 60_000)).toBe("4 min");
    expect(formatDuration(2 * 3_600_000 + 5 * 60_000)).toBe("2 h 05");
    expect(formatDuration(27 * 3_600_000)).toBe("1 j 3 h");
  });

  it("labels open alerts with « depuis » and resolved ones with their total duration", () => {
    const open = makeAlert({ opened_at: new Date(ALERTS_NOW_MS - 4 * 60_000).toISOString() });
    expect(durationLabel(open, ALERTS_NOW_MS)).toBe("depuis 4 min");
    const resolved = makeAlert({
      opened_at: new Date(ALERTS_NOW_MS - 20 * 60_000).toISOString(),
      resolved_at: new Date(ALERTS_NOW_MS - 8 * 60_000).toISOString(),
      resolved_value: 29.1,
    });
    expect(durationLabel(resolved, ALERTS_NOW_MS)).toBe("12 min");
  });

  it("sorts open alerts first, then newest first", () => {
    const oldResolved = makeAlert({
      id: "a",
      opened_at: "2026-10-06T07:00:00Z",
      resolved_at: "2026-10-06T07:10:00Z",
    });
    const newResolved = makeAlert({
      id: "b",
      opened_at: "2026-10-06T08:00:00Z",
      resolved_at: "2026-10-06T08:10:00Z",
    });
    const open = makeAlert({ id: "c", opened_at: "2026-10-06T06:00:00Z" });
    expect(sortAlerts([oldResolved, newResolved, open]).map((a) => a.id)).toEqual(["c", "b", "a"]);
  });

  it("upserts by id and keeps an unknown resolved alert", () => {
    const open = makeAlert({ id: "x" });
    const list = upsert([], open);
    const resolved = { ...open, resolved_at: "2026-10-06T09:05:00Z", resolved_value: 29 };
    expect(upsert(list, resolved)).toEqual([resolved]);
    const stranger = makeAlert({ id: "y", resolved_at: "2026-10-06T09:06:00Z" });
    expect(upsert(list, stranger).map((a) => a.id)).toEqual(["x", "y"]);
  });

  it("splits the description into peak, bound and excess for the tiles", () => {
    const high = makeAlert();
    expect(peakLabel(high)).toBe("31,2 °C");
    expect(boundLabel(high)).toBe("30 °C");
    expect(excessLabel(high)).toBe("+1,2 °C");
    const low = makeAlert({ metric: "humidity", direction: "low", threshold: 20, peak_value: 12 });
    expect(excessLabel(low)).toBe("−8 pts");
    const flag = makeAlert({ metric: "gas", threshold: 0, peak_value: 1600 });
    expect(boundLabel(flag)).toBeNull();
    expect(excessLabel(flag)).toBeNull();
  });

  it("labels days relative to now and groups a timeline by day", () => {
    const now = ALERTS_NOW_MS;
    expect(dayLabel(now - 60_000, now)).toBe("Aujourd'hui");
    expect(dayLabel(now - 86_400_000, now)).toBe("Hier");
    expect(dayLabel(now - 3 * 86_400_000, now)).toMatch(/oct\./);
    const groups = groupByDay(
      [
        makeAlert({ id: "a", opened_at: new Date(now - 60_000).toISOString() }),
        makeAlert({ id: "b", opened_at: new Date(now - 90_000).toISOString() }),
        makeAlert({ id: "c", opened_at: new Date(now - 86_400_000).toISOString() }),
      ],
      now,
    );
    expect(groups.map((g) => [g.label, g.alerts.map((a) => a.id)])).toEqual([
      ["Aujourd'hui", ["a", "b"]],
      ["Hier", ["c"]],
    ]);
  });

  it("summarises open count, last 24 h and the most frequent metric", () => {
    const now = ALERTS_NOW_MS;
    const summary = summarize(
      [
        makeAlert({ id: "a" }),
        makeAlert({ id: "b", metric: "humidity", resolved_at: new Date(now).toISOString() }),
        makeAlert({
          id: "c",
          metric: "humidity",
          opened_at: new Date(now - 2 * 86_400_000).toISOString(),
          resolved_at: new Date(now - 2 * 86_400_000 + 60_000).toISOString(),
        }),
      ],
      now,
    );
    expect(summary).toEqual({ open: 1, last24h: 2, topMetric: "humidity" });
    expect(summarize([], now)).toEqual({ open: 0, last24h: 0, topMetric: null });
  });
});
