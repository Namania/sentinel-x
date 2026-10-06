import { useSyncExternalStore } from "react";

/**
 * The current time, rounded down to `stepMs`, re-rendering when the step changes. Rounding keeps
 * the snapshot stable between calls (React requires it) and makes « depuis 4 min » tick on a wall
 * screen without a timer per row.
 */
export function useNow(stepMs = 30_000): number {
  return useSyncExternalStore(
    (onChange) => {
      const timer = setInterval(onChange, stepMs);
      return () => clearInterval(timer);
    },
    () => Math.floor(Date.now() / stepMs) * stepMs,
    () => Math.floor(Date.now() / stepMs) * stepMs,
  );
}
