import { useContext, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { RealtimeContext } from "./realtime-context";

export const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000] as const;

export function streamUrl(token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
}

/**
 * Events of the app WebSocket, `{ type, data }`, filtered by the caller. Inside a
 * `RealtimeProvider` every call shares its single socket; outside (tests), each call opens one.
 */
export function useEventStream(enabled: boolean, onEvent: (type: string, data: unknown) => void) {
  const shared = useContext(RealtimeContext);
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);
  useEffect(() => {
    if (!shared || !enabled) return;
    return shared.subscribe((type, data) => onEventRef.current(type, data));
  }, [shared, enabled]);
  const standalone = useStandaloneEventStream(enabled && shared === null, onEvent);
  return { connected: shared ? enabled && shared.connected : standalone.connected };
}

/**
 * One WebSocket of its own: reconnects with growing waits, reopens when the access token changes,
 * closes on unmount or when disabled. The provider is built on it.
 */
export function useStandaloneEventStream(
  enabled: boolean,
  onEvent: (type: string, data: unknown) => void,
) {
  const { accessToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled || !accessToken) return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(streamUrl(accessToken));
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as { type?: unknown; data?: unknown };
          if (typeof message.type === "string") onEventRef.current(message.type, message.data);
        } catch {
          // Not JSON: ignore.
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (stopped) return;
        const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]!;
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
      setConnected(false);
    };
  }, [enabled, accessToken]);

  return { connected };
}
