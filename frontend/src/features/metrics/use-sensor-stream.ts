import { useCallback } from "react";
import { useEventStream } from "@/features/realtime/use-event-stream";
import type { Reading } from "./metrics-api";

export { RECONNECT_DELAYS_MS, streamUrl } from "@/features/realtime/use-event-stream";

/** `sensor.reading` events of the app WebSocket. */
export function useSensorStream(enabled: boolean, onReading: (reading: Reading) => void) {
  const onEvent = useCallback(
    (type: string, data: unknown) => {
      if (type === "sensor.reading" && data) onReading(data as Reading);
    },
    [onReading],
  );
  return useEventStream(enabled, onEvent);
}
