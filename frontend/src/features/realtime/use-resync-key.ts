import { useEffect, useRef, useState } from "react";

/**
 * A counter that increments each time `connected` goes back to true after a drop. Hooks that
 * cache server state put it in their fetch effect's dependencies: events emitted while the
 * socket was down are gone for good, so the only honest move is to reload after a reconnect.
 */
export function useResyncKey(connected: boolean): number {
  const [key, setKey] = useState(0);
  const wasConnected = useRef(false);
  useEffect(() => {
    if (connected && wasConnected.current) setKey((k) => k + 1);
    if (connected) wasConnected.current = true;
  }, [connected]);
  return key;
}
