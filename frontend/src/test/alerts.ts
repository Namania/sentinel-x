import type { Alert } from "@/features/alerts/alerts-api";

export const ALERTS_NOW_MS = Date.UTC(2026, 9, 6, 9, 0, 0);

export function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: "alert-1",
    device_id: "esp-interieur",
    metric: "temperature",
    direction: "high",
    threshold: 30,
    opened_at: new Date(ALERTS_NOW_MS - 4 * 60_000).toISOString(),
    opened_value: 30.4,
    peak_value: 31.2,
    resolved_at: null,
    resolved_value: null,
    ...overrides,
  };
}

/** Default API state in tests: one resolved humidity alert, nothing open. */
export function alertsFixture(): Alert[] {
  return [
    makeAlert({
      id: "alert-resolved",
      metric: "humidity",
      direction: "high",
      threshold: 70,
      opened_value: 71,
      peak_value: 74,
      opened_at: new Date(ALERTS_NOW_MS - 60 * 60_000).toISOString(),
      resolved_at: new Date(ALERTS_NOW_MS - 48 * 60_000).toISOString(),
      resolved_value: 67,
    }),
  ];
}
