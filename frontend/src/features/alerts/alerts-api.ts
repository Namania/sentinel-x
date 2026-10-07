import { formatDuration, formatNumber } from "@/lib/format-number";

export { formatDuration };

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
/** The API's maximum; the /alertes page says so when the history is longer. */
export const ALERTS_LIMIT = 500;
/** Resolved alerts shown on the dashboard card, after the open ones. */
export const RESOLVED_SHOWN = 5;

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
  if (alert.metric === "gas" && alert.threshold === 0) {
    // Raised by the device's own flag: no bound to compare with, show the level if we have one.
    return alert.peak_value > 0
      ? `alerte ESP (${formatNumber(alert.peak_value, 0)} mV)`
      : "alerte ESP";
  }
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
  if (alert.metric === "gas" && alert.threshold === 0)
    return `${label} : ${valueAgainstBound(alert)}`;
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

export function durationLabel(alert: Alert, nowMs: number): string {
  const opened = Date.parse(alert.opened_at);
  if (alert.resolved_at === null) return `depuis ${formatDuration(nowMs - opened)}`;
  return formatDuration(Date.parse(alert.resolved_at) - opened);
}
