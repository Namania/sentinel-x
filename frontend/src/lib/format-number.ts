const formatters = new Map<number, Intl.NumberFormat>();

function formatter(digits: number): Intl.NumberFormat {
  let f = formatters.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("fr-FR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    formatters.set(digits, f);
  }
  return f;
}

/** "22,5" — or an en dash when there is no value. */
export function formatNumber(value: number | null | undefined, digits: number): string {
  return value === null || value === undefined ? "–" : formatter(digits).format(value);
}

/** Signed variation, "+0,6" / "−0,6", or null when one side is missing. */
export function formatDelta(
  current: number | null,
  previous: number | null,
  digits: number,
): string | null {
  if (current === null || previous === null) return null;
  const delta = current - previous;
  const magnitude = formatter(digits).format(Math.abs(delta));
  if (Math.round(Math.abs(delta) * 10 ** digits) === 0) return magnitude;
  return `${delta < 0 ? "−" : "+"}${magnitude}`;
}

const TIME = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** "11:05" — or an en dash when the value is not a valid time. */
export function formatTime(ms: number): string {
  return Number.isFinite(ms) ? TIME.format(new Date(ms)) : "–";
}

/** « 4 min », « 2 h 05 », « 1 j 3 h » — or « moins d'une minute ». */
export function formatDuration(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "moins d'une minute";
  const hours = Math.floor(minutes / 60);
  if (hours < 1) return `${minutes} min`;
  const days = Math.floor(hours / 24);
  if (days < 1) return `${hours} h ${String(minutes % 60).padStart(2, "0")}`;
  return `${days} j ${hours % 24} h`;
}
