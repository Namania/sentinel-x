import { useCallback, useMemo, useRef, type ReactNode } from "react";
import { RealtimeContext, type EventListener } from "./realtime-context";
import { useStandaloneEventStream } from "./use-event-stream";

/**
 * Opens the app WebSocket once and fans every message out to the hooks that subscribed.
 * Without it each `useEventStream` call opens its own socket (that fallback is what tests use).
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<EventListener>());
  const fanOut = useCallback((type: string, data: unknown) => {
    listeners.current.forEach((listener) => listener(type, data));
  }, []);
  const { connected } = useStandaloneEventStream(true, fanOut);
  const subscribe = useCallback((listener: EventListener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);
  const api = useMemo(() => ({ subscribe, connected }), [subscribe, connected]);
  return <RealtimeContext.Provider value={api}>{children}</RealtimeContext.Provider>;
}
