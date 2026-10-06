import { formatNumber } from "@/lib/format-number";

export type Metric = "temperature" | "humidity" | "gas";
export type Direction = "low" | "high";

export type Alert = {
  id: string;
  device_id: string;
  metric: Metric;
  direction: Direction;
  threshold: number;
  opened_at: string;
  opened_value: number;
  peak_value: number;
  resolved_at: string | null;
  resolved_value: number | null;
};

export const ALERTS_PATH = "/alerts";
export const ALERTS_SUMMARY_PATH = "/alerts/summary";
export const ALERTS_LIMIT = 200;

export function alertsPath(limit = ALERTS_LIMIT): string {
  return `${ALERTS_PATH}?limit=${limit}`;
}

export const METRIC_LABELS: Record<Metric, string> = {
  temperature: "Température",
  humidity: "Humidité",
  gas: "Gaz",
};
export const UNITS: Record<Metric, string> = { temperature: "°C", humidity: "%", gas: "mV" };
export const DIGITS: Record<Metric, number> = { temperature: 1, humidity: 0, gas: 0 };

export function isOpen(alert: Alert): boolean {
  return alert.resolved_at === null;
}

/** « 31,2 °C > 30 °C » — the peak against the bound, or « alerte ESP » when only the flag spoke. */
export function valueAgainstBound(alert: Alert): string {
  if (alert.metric === "gas" && alert.threshold === 0) return "alerte ESP";
  const unit = UNITS[alert.metric];
  const digits = DIGITS[alert.metric];
  const sign = alert.direction === "high" ? ">" : "<";
  // The bound is a setting (« 30 °C »), shown without decimals unless it has some.
  const boundDigits = Number.isInteger(alert.threshold) ? 0 : digits;
  return `${formatNumber(alert.peak_value, digits)} ${unit} ${sign} ${formatNumber(alert.threshold, boundDigits)} ${unit}`;
}

/** « Température 31,2 °C > 30 °C » — or « Gaz : alerte ESP » when only the device flag spoke. */
export function describeAlert(alert: Alert): string {
  const label = METRIC_LABELS[alert.metric];
  if (alert.metric === "gas" && alert.threshold === 0) return `${label} : alerte ESP`;
  return `${label} ${valueAgainstBound(alert)}`;
}

export function sortAlerts(alerts: Alert[]): Alert[] {
  return [...alerts].sort((a, b) => {
    if (isOpen(a) !== isOpen(b)) return isOpen(a) ? -1 : 1;
    return Date.parse(b.opened_at) - Date.parse(a.opened_at);
  });
}

/** Replace the alert with the same id, or add it; always returns a sorted copy. */
export function upsert(alerts: Alert[], alert: Alert): Alert[] {
  const others = alerts.filter((a) => a.id !== alert.id);
  return sortAlerts([...others, alert]);
}

export function formatDuration(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "moins d'une minute";
  const hours = Math.floor(minutes / 60);
  if (hours < 1) return `${minutes} min`;
  const days = Math.floor(hours / 24);
  if (days < 1) return `${hours} h ${String(minutes % 60).padStart(2, "0")}`;
  return `${days} j ${hours % 24} h`;
}

export function durationLabel(alert: Alert, nowMs: number): string {
  const opened = Date.parse(alert.opened_at);
  if (alert.resolved_at === null) return `depuis ${formatDuration(nowMs - opened)}`;
  return formatDuration(Date.parse(alert.resolved_at) - opened);
}
