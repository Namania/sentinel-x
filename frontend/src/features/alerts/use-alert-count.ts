import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import { ALERTS_SUMMARY_PATH } from "./alerts-api";

/** Number of open alerts for the nav badge; null until the summary has loaded. */
export function useAlertCount(): number | null {
  const { authFetch } = useAuth();
  const [count, setCount] = useState<number | null>(null);

  const onEvent = useCallback((type: string) => {
    if (type === "alert.opened") setCount((c) => (c ?? 0) + 1);
    if (type === "alert.resolved") setCount((c) => Math.max(0, (c ?? 1) - 1));
  }, []);
  const { connected } = useEventStream(true, onEvent);
  // Events missed while the socket was down would leave a wrong count: reload after a reconnect.
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    authFetch<{ open: number }>(ALERTS_SUMMARY_PATH)
      .then((summary) => {
        if (!cancelled) setCount(summary.open);
      })
      .catch(() => {
        // Keep whatever we had; the next event will adjust it.
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  return count;
}
