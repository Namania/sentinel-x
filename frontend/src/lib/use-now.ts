import { useSyncExternalStore } from "react";

/**
 * The current time, rounded down to `stepMs`, re-rendering exactly when the step changes.
 * Rounding keeps the snapshot stable between calls (React requires it) and makes « depuis 4 min »
 * tick on a wall screen without a timer per row.
 */
export function useNow(stepMs = 30_000): number {
  return useSyncExternalStore(
    (onChange) => {
      let timer: ReturnType<typeof setTimeout>;
      const schedule = () => {
        // Wake up at the next boundary, not `stepMs` after mount: no lag up to a full step.
        timer = setTimeout(
          () => {
            onChange();
            schedule();
          },
          stepMs - (Date.now() % stepMs),
        );
      };
      schedule();
      return () => clearTimeout(timer);
    },
    () => Math.floor(Date.now() / stepMs) * stepMs,
    () => Math.floor(Date.now() / stepMs) * stepMs,
  );
}
