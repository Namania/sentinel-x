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

export type DayGroup<T> = { label: string; items: T[] };

/** Items grouped by the day of `at(item)`, in the order given (newest day first when sorted). */
export function groupByDay<T>(items: T[], nowMs: number, at: (item: T) => string): DayGroup<T>[] {
  const groups: DayGroup<T>[] = [];
  for (const item of items) {
    const label = dayLabel(Date.parse(at(item)), nowMs);
    const last = groups.at(-1);
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}
