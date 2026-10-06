import { createContext } from "react";

export type EventListener = (type: string, data: unknown) => void;

export type RealtimeApi = {
  /** Register for every `{ type, data }` message; returns the unsubscribe function. */
  subscribe: (listener: EventListener) => () => void;
  connected: boolean;
};

/** One WebSocket for the whole authenticated area; null outside the provider (tests, fallback). */
export const RealtimeContext = createContext<RealtimeApi | null>(null);
