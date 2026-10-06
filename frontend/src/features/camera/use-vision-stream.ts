import { useEffect, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { streamUrl } from "@/features/metrics/use-sensor-stream";
import type { DetectionSnapshot } from "./vision-api";

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000] as const;

/**
 * Listen to `vision.detection` events on the app WebSocket (person detection + face whitelist
 * results, pushed by the backend's vision worker). Reconnects with growing waits, reopens when
 * the access token changes, closes on unmount or when disabled.
 */
export function useVisionStream(enabled: boolean): DetectionSnapshot | null {
  const { accessToken } = useAuth();
  const [snapshot, setSnapshot] = useState<DetectionSnapshot | null>(null);

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
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as {
            type?: string;
            data?: DetectionSnapshot;
          };
          if (message.type === "vision.detection" && message.data) {
            setSnapshot(message.data);
          }
        } catch {
          // Not JSON: ignore.
        }
      };
      socket.onclose = () => {
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
      setSnapshot(null);
    };
  }, [enabled, accessToken]);

  return snapshot;
}
