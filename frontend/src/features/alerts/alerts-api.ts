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
export const RESOLVED_SHOWN = 3;

export function alertsPath(limit = ALERTS_LIMIT): string {
  return `${ALERTS_PATH}?limit=${limit}`;
}

export const METRIC_LABELS: Record<Metric, string> = {
  temperature: "Température",
  humidity: "Humidité",
  gas: "Gaz",
};
export const UNITS: Record<Metric, string> = {
  temperature: "°C",
  humidity: "%",
  gas: "mV",
};
export const DIGITS: Record<Metric, number> = {
  temperature: 1,
  humidity: 0,
  gas: 0,
};

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

/** « moins d'une minute », then « 4 min »… — the page clock ticks every 30 s, seconds would lie. */
export function sinceLabel(ms: number): string {
  return ms < 60_000 ? "moins d'une minute" : formatDuration(ms);
}

export function durationLabel(alert: Alert, nowMs: number): string {
  const opened = Date.parse(alert.opened_at);
  if (alert.resolved_at === null) return `depuis ${sinceLabel(nowMs - opened)}`;
  return formatDuration(Date.parse(alert.resolved_at) - opened);
}

export const METRIC_COLORS: Record<Metric, string> = {
  temperature: "var(--metric-temperature)",
  humidity: "var(--metric-humidity)",
  gas: "var(--metric-gas)",
};

/** « 31,2 °C », « 78 % », « 1 800 mV » — the peak with its unit. */
export function peakLabel(alert: Alert): string {
  return `${formatNumber(alert.peak_value, DIGITS[alert.metric])} ${UNITS[alert.metric]}`;
}

/** « 30 °C » — the bound as the settings state it; null for a flag-only gas alert. */
export function boundLabel(alert: Alert): string | null {
  if (alert.metric === "gas" && alert.threshold === 0) return null;
  const digits = Number.isInteger(alert.threshold) ? 0 : DIGITS[alert.metric];
  return `${formatNumber(alert.threshold, digits)} ${UNITS[alert.metric]}`;
}

/** « +8 pts », « +3,0 °C », « −2 pts » — how far the peak went past the bound. */
export function excessLabel(alert: Alert): string | null {
  if (alert.metric === "gas" && alert.threshold === 0) return null;
  const delta = alert.peak_value - alert.threshold;
  const digits = DIGITS[alert.metric];
  const unit = alert.metric === "humidity" ? "pts" : UNITS[alert.metric];
  const sign = delta < 0 ? "−" : "+";
  return `${sign}${formatNumber(Math.abs(delta), digits)} ${unit}`;
}

/** « 10:51 → 10:52 » for a resolved alert, « 10:51 → … » while open. */
export function timeRange(alert: Alert, format: (ms: number) => string): string {
  const opened = format(Date.parse(alert.opened_at));
  return alert.resolved_at
    ? `${opened} → ${format(Date.parse(alert.resolved_at))}`
    : `${opened} → …`;
}

const DAY_LABEL = new Intl.DateTimeFormat("fr-FR", {
  weekday: "short",
  day: "numeric",
  month: "short",
});

function localDay(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** « Aujourd'hui », « Hier », then « lun. 6 oct. » — for grouping a timeline by day. */
export function dayLabel(ms: number, nowMs: number): string {
  if (localDay(ms) === localDay(nowMs)) return "Aujourd'hui";
  if (localDay(ms) === localDay(nowMs - 86_400_000)) return "Hier";
  return DAY_LABEL.format(new Date(ms));
}

export type DayGroup = { label: string; alerts: Alert[] };

/** Alerts grouped by the day they opened, newest day first; input order is kept inside a day. */
export function groupByDay(alerts: Alert[], nowMs: number): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const alert of alerts) {
    const label = dayLabel(Date.parse(alert.opened_at), nowMs);
    const last = groups.at(-1);
    if (last && last.label === label) last.alerts.push(alert);
    else groups.push({ label, alerts: [alert] });
  }
  return groups;
}

export type AlertSummary = { open: number; last24h: number; topMetric: Metric | null };

export function summarize(alerts: Alert[], nowMs: number): AlertSummary {
  const counts: Record<Metric, number> = { temperature: 0, humidity: 0, gas: 0 };
  let last24h = 0;
  for (const a of alerts) {
    counts[a.metric] += 1;
    if (nowMs - Date.parse(a.opened_at) <= 86_400_000) last24h += 1;
  }
  const top = (Object.keys(counts) as Metric[]).sort((a, b) => counts[b] - counts[a])[0]!;
  return { open: alerts.filter(isOpen).length, last24h, topMetric: counts[top] > 0 ? top : null };
}
