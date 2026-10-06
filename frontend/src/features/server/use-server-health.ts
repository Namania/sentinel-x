import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
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

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
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
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "server.health" || !data) return;
    const sample = data as ServerHealth;
    if (!loaded.current) {
      pending.current = appendHealth(pending.current, sample);
      return;
    }
    setHistory((current) => appendHealth(current, sample));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);

  return { status, latest: history.at(-1) ?? null, history, connected };
}
