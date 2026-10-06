import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import type { Reading } from "./metrics-api";

export const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000] as const;

export function streamUrl(token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
}

/**
 * Listen to `sensor.reading` events on the app WebSocket. Reconnects with growing waits,
 * reopens when the access token changes, closes on unmount or when disabled.
 */
export function useSensorStream(enabled: boolean, onReading: (reading: Reading) => void) {
  const { accessToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const onReadingRef = useRef(onReading);
  useEffect(() => {
    onReadingRef.current = onReading;
  }, [onReading]);

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
          const message = JSON.parse(String(event.data)) as { type?: string; data?: Reading };
          if (message.type === "sensor.reading" && message.data) {
            onReadingRef.current(message.data);
          }
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
