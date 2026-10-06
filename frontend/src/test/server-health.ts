import type { ServerHealth } from "@/features/server/server-api";

export const SERVER_NOW_MS = Date.UTC(2026, 9, 6, 9, 0, 0);

export function makeHealth(overrides: Partial<ServerHealth> = {}): ServerHealth {
  return {
    recorded_at: new Date(SERVER_NOW_MS).toISOString(),
    cpu_pct: 12.5,
    mem_total_bytes: 8 * 2 ** 30,
    mem_used_bytes: 2 * 2 ** 30,
    disk_total_bytes: 64 * 2 ** 30,
    disk_used_bytes: 20 * 2 ** 30,
    temperature_c: 48.2,
    load_1: 0.42,
    load_5: 0.38,
    load_15: 0.31,
    uptime_s: 3 * 86_400 + 4 * 3600,
    ...overrides,
  };
}

/** n samples `stepMs` apart ending at `endMs`; the first one has no CPU value, like the real API. */
export function healthFixture(n: number, endMs: number, stepMs = 5000): ServerHealth[] {
  return Array.from({ length: n }, (_, i) =>
    makeHealth({
      recorded_at: new Date(endMs - (n - 1 - i) * stepMs).toISOString(),
      cpu_pct: i === 0 ? null : 10 + i,
      uptime_s: 3 * 86_400 + 4 * 3600 + (i * stepMs) / 1000,
    }),
  );
}
