import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import { alertsPath, isOpen, sortAlerts, upsert, type Alert } from "./alerts-api";

type Status = "loading" | "ready" | "error";

/** The alert list, kept live by `alert.opened` / `alert.resolved` events. */
export function useAlerts(enabled = true) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  // Events that arrive before the list response; merged once it lands.
  const pending = useRef<Alert[]>([]);
  const loaded = useRef(false);
  // Set when the list request failed; the first live event then rebuilds the state.
  const failed = useRef(false);

  const onEvent = useCallback((type: string, data: unknown) => {
    if ((type !== "alert.opened" && type !== "alert.resolved") || !data) return;
    const alert = data as Alert;
    if (!loaded.current && !failed.current) {
      pending.current = upsert(pending.current, alert);
      return;
    }
    if (failed.current) {
      // The list request failed: live events are enough to carry on with what we have.
      failed.current = false;
      loaded.current = true;
      const seeded = upsert(pending.current, alert);
      pending.current = [];
      setAlerts((current) => seeded.reduce((acc, a) => upsert(acc, a), current));
      setStatus("ready");
      return;
    }
    setAlerts((current) => upsert(current, alert));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);
  // Events emitted while the socket was down are lost: reload the list after each reconnect.
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
    failed.current = false;
    authFetch<Alert[]>(alertsPath())
      .then((list) => {
        if (cancelled) return;
        const merged = pending.current.reduce((acc, a) => upsert(acc, a), sortAlerts(list));
        pending.current = [];
        loaded.current = true;
        setAlerts(merged);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        failed.current = true;
        // A failed resync keeps the data we already show; a failed first load reports it.
        setStatus((current) => (current === "ready" ? current : "error"));
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  return { status, alerts, open: alerts.filter(isOpen), connected };
}
