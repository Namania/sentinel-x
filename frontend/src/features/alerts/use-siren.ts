import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import { SIREN_MUTE_PATH, SIREN_PATH, type SirenState } from "./siren-api";

type Status = "loading" | "ready" | "error";

/** The siren state, live, with its two actions. Events are authoritative; a response shows at once. */
export function useSiren() {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [state, setState] = useState<SirenState | null>(null);
  const [pending, setPending] = useState(false);
  // Last failed action, for the person standing next to the buzzer; cleared on the next try.
  const [error, setError] = useState<string | null>(null);
  const loaded = useRef(false);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "siren.state" || !data) return;
    loaded.current = true;
    setState(data as SirenState);
    setStatus("ready");
  }, []);
  const { connected } = useEventStream(true, onEvent);
  // An event emitted while the socket was down is lost: reload after a reconnect.
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    authFetch<SirenState>(SIREN_PATH)
      .then((fresh) => {
        if (cancelled) return;
        loaded.current = true;
        setState(fresh);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled && !loaded.current) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  const call = useCallback(
    async (method: "POST" | "DELETE") => {
      setPending(true);
      setError(null);
      try {
        const fresh = await authFetch<SirenState>(SIREN_MUTE_PATH, { method });
        setState(fresh);
        setStatus("ready");
      } catch {
        // The bar keeps the previous state and says so; the next event will settle it.
        setError("Échec, réessayez");
      } finally {
        setPending(false);
      }
    },
    [authFetch],
  );
  const mute = useCallback(() => call("POST"), [call]);
  const unmute = useCallback(() => call("DELETE"), [call]);

  return { status, state, connected, pending, error, mute, unmute };
}
