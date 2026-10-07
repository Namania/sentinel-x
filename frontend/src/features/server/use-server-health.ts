import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import {
  appendHealth,
  SERVER_HEALTH_PATH,
  type ServerHealth,
  type ServerHealthResponse,
} from "./server-api";

type Status = "loading" | "ready" | "error";

/** Server health history (30 min) kept up to date by `server.health` WebSocket events. */
export function useServerHealth(enabled = true) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [history, setHistory] = useState<ServerHealth[]>([]);
  // Events that arrive before the history response; merged once it lands.
  const pending = useRef<ServerHealth[]>([]);
  const loaded = useRef(false);
  // Set when the history request failed; the first live sample then rebuilds the state.
  const failed = useRef(false);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "server.health" || !data) return;
    const sample = data as ServerHealth;
    if (!loaded.current && !failed.current) {
      pending.current = appendHealth(pending.current, sample);
      return;
    }
    if (failed.current) {
      // The history request failed (API restarting?): live samples are enough to recover with.
      failed.current = false;
      loaded.current = true;
      const seeded = appendHealth(pending.current, sample);
      pending.current = [];
      setHistory(seeded);
      setStatus("ready");
      return;
    }
    setHistory((current) => appendHealth(current, sample));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);
  // Samples emitted while the socket was down are lost: reload the history after a reconnect.
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
    failed.current = false;
    authFetch<ServerHealthResponse>(SERVER_HEALTH_PATH)
      .then((response) => {
        if (cancelled) return;
        const merged = pending.current.reduce(
          (acc, sample) => appendHealth(acc, sample),
          response.history,
        );
        pending.current = [];
        loaded.current = true;
        setHistory(merged);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        failed.current = true;
        setStatus((current) => (current === "ready" ? current : "error"));
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  return { status, latest: history.at(-1) ?? null, history, connected };
}
