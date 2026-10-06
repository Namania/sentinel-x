import { describe, expect, it } from "vitest";
import { healthFixture, makeHealth, SERVER_NOW_MS } from "@/test/server-health";
import {
  appendHealth,
  formatBytes,
  formatBytesPair,
  formatPct,
  formatTemperature,
  formatUptime,
  ratio,
} from "./server-api";

describe("server api helpers", () => {
  it("appends newer samples and drops the oldest beyond maxlen", () => {
    const history = healthFixture(3, SERVER_NOW_MS);
    const next = makeHealth({ recorded_at: new Date(SERVER_NOW_MS + 5000).toISOString() });
    const result = appendHealth(history, next, 3);
    expect(result).toHaveLength(3);
    expect(result.at(-1)).toBe(next);
    expect(result[0]).toBe(history[1]);
  });

  it("ignores a sample that is not newer than the last one", () => {
    const history = healthFixture(2, SERVER_NOW_MS);
    const duplicate = makeHealth({ recorded_at: history[1]!.recorded_at });
    expect(appendHealth(history, duplicate)).toBe(history);
  });

  it("computes a usage ratio, null without a total", () => {
    expect(ratio(2, 8)).toBeCloseTo(0.25);
    expect(ratio(0, 0)).toBeNull();
  });

  it("formats percentages, bytes, temperatures and uptimes in French", () => {
    expect(formatPct(12.49)).toBe("12 %");
    expect(formatPct(null)).toBe("–");
    expect(formatBytes(2 * 2 ** 30)).toBe("2,0 Gio");
    expect(formatBytesPair(2 * 2 ** 30, 8 * 2 ** 30)).toBe("2,0 / 8,0 Gio");
    expect(formatTemperature(48.26)).toBe("48,3 °C");
    expect(formatTemperature(null)).toBe("–");
    expect(formatUptime(3 * 86_400 + 4 * 3600 + 7 * 60)).toBe("3 j 4 h");
    expect(formatUptime(4 * 3600 + 12 * 60)).toBe("4 h 12 min");
    expect(formatUptime(12 * 60 + 30)).toBe("12 min");
    expect(formatUptime(30)).toBe("< 1 min");
  });
});
