import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import { prepend, sshEventsPath, type SshEvent } from "./ssh-api";

type Status = "loading" | "ready" | "error";

/** The SSH connection log, newest first, kept live by `ssh.event` events. */
export function useSshEvents(enabled = true) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [events, setEvents] = useState<SshEvent[]>([]);
  // Events that arrive before the list response; merged once it lands.
  const pending = useRef<SshEvent[]>([]);
  const loaded = useRef(false);
  // Set when the list request failed; the first live event then rebuilds the state.
  const failed = useRef(false);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "ssh.event" || !data) return;
    const event = data as SshEvent;
    if (!loaded.current && !failed.current) {
      pending.current = prepend(pending.current, event);
      return;
    }
    if (failed.current) {
      // The list request failed: live events are enough to carry on with what we have.
      failed.current = false;
      loaded.current = true;
      const seeded = prepend(pending.current, event);
      pending.current = [];
      setEvents((current) => seeded.reduce((acc, e) => prepend(acc, e), current));
      setStatus("ready");
      return;
    }
    setEvents((current) => prepend(current, event));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);
  // Events emitted while the socket was down are lost: reload the list after each reconnect.
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
    failed.current = false;
    authFetch<SshEvent[]>(sshEventsPath())
      .then((list) => {
        if (cancelled) return;
        const sorted = [...list].sort(
          (a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at),
        );
        const merged = pending.current.reduce((acc, e) => prepend(acc, e), sorted);
        pending.current = [];
        loaded.current = true;
        setEvents(merged);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        failed.current = true;
        // A failed resync keeps the data we already show; a failed first load reports it.
        setStatus((current) => (current === "ready" ? current : "error"));
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  return { status, events, connected };
}
