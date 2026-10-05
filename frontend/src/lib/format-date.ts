const LONG_DATE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long" });

/** "2026-10-05T10:00:00Z" → "5 octobre 2026" (local time zone). */
export function formatLongDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : LONG_DATE.format(date);
}
