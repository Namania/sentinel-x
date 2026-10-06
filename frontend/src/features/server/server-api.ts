import { formatNumber } from "@/lib/format-number";

export type ServerHealth = {
  recorded_at: string;
  cpu_pct: number | null;
  mem_total_bytes: number;
  mem_used_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  temperature_c: number | null;
  load_1: number;
  load_5: number;
  load_15: number;
  uptime_s: number;
};

export type ServerHealthResponse = { latest: ServerHealth | null; history: ServerHealth[] };

export const SERVER_HEALTH_PATH = "/server/health";
export const HISTORY_MAXLEN = 360;
/** Above these, a gauge's bar turns to the destructive colour; the value is always shown too. */
export const USAGE_WARN_PCT = 85;
export const TEMPERATURE_WARN_C = 70;

/** History plus one live sample, oldest first, bounded; not-newer samples are ignored. */
export function appendHealth(
  history: ServerHealth[],
  sample: ServerHealth,
  maxlen = HISTORY_MAXLEN,
): ServerHealth[] {
  const last = history.at(-1);
  if (last && Date.parse(sample.recorded_at) <= Date.parse(last.recorded_at)) return history;
  return [...history, sample].slice(-maxlen);
}

export function ratio(used: number, total: number): number | null {
  return total > 0 ? used / total : null;
}

export function formatPct(value: number | null): string {
  return value === null ? "–" : `${formatNumber(value, 0)} %`;
}

export function formatBytes(bytes: number): string {
  return `${formatNumber(bytes / 2 ** 30, 1)} Gio`;
}

/** "2,0 / 8,0 Gio" — used and total share the unit. */
export function formatBytesPair(used: number, total: number): string {
  return `${formatNumber(used / 2 ** 30, 1)} / ${formatNumber(total / 2 ** 30, 1)} Gio`;
}

export function formatTemperature(celsius: number | null): string {
  return celsius === null ? "–" : `${formatNumber(celsius, 1)} °C`;
}

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days} j ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return `${minutes} min`;
  return "< 1 min";
}

/** "Charge 0,42 · 0,38 · 0,31" as one text node so tests and screen readers get one phrase. */
export function loadLabel(h: ServerHealth): string {
  return `Charge ${formatNumber(h.load_1, 2)} · ${formatNumber(h.load_5, 2)} · ${formatNumber(h.load_15, 2)}`;
}
