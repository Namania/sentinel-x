import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { API_BASE } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CAMERA_STATUS_PATH, type CameraStatus } from "./camera-api";
import { boundaryFromContentType, MjpegFrames } from "./mjpeg-reader";

export const RECONNECT_DELAY_MS = 2000;
/** No frame for this long while connected → the stream is reopened. */
export const STALL_MS = 5000;
export const STREAM_PATH = "/camera/stream";

export type StreamState = "checking" | "unconfigured" | "connecting" | "live";

type Props = {
  onStateChange?: (state: StreamState) => void;
  onStatus?: (status: CameraStatus) => void;
  className?: string;
  stallMs?: number;
  /** Receives the stream's <img>, e.g. to draw detection boxes over it. */
  imageRef?: React.RefObject<HTMLImageElement | null>;
};

/**
 * The relayed MJPEG stream, read with `fetch` and shown one frame at a time through an <img>.
 *
 * A plain `<img src=stream>` decodes every frame it receives, in order: when frames arrive faster
 * than the browser draws them, the delay grows for as long as the page stays open. Here a frame
 * that arrives while the previous one is still decoding replaces the pending one instead, so the
 * picture is always the newest and the latency stays bounded. Reconnects 2 s after a failure or
 * when no frame arrived for `stallMs`; releases everything on unmount. Renders nothing when no
 * camera is configured; the parent decides what to say.
 */
export function CameraStream({
  onStateChange,
  onStatus,
  className,
  stallMs = STALL_MS,
  imageRef,
}: Props) {
  const { accessToken, authFetch } = useAuth();
  const tokenRef = useRef(accessToken);
  // Set when the stream should open but the session token has not been committed yet.
  const pendingConnect = useRef(false);
  const [state, setStateRaw] = useState<StreamState>("checking");
  const [src, setSrc] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stallTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Frame display: one decode at a time, the newest frame waits its turn, older ones are dropped.
  const busy = useRef(false);
  const pending = useRef<Uint8Array | null>(null);
  const shownUrl = useRef<string | null>(null);
  const onStateChangeRef = useRef(onStateChange);
  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStateChangeRef.current = onStateChange;
    onStatusRef.current = onStatus;
  });

  const setState = useCallback((next: StreamState) => {
    setStateRaw(next);
    onStateChangeRef.current?.(next);
  }, []);

  const display = useCallback((frame: Uint8Array) => {
    busy.current = true;
    const url = URL.createObjectURL(new Blob([frame as BlobPart], { type: "image/jpeg" }));
    setSrc(url);
  }, []);

  const connect = useCallback(() => {
    if (!tokenRef.current) {
      pendingConnect.current = true;
      return;
    }
    pendingConnect.current = false;
    controller.current?.abort();
    if (stallTimer.current) clearTimeout(stallTimer.current);
    const abort = new AbortController();
    controller.current = abort;
    setState("connecting");

    const armStallTimer = () => {
      if (stallTimer.current) clearTimeout(stallTimer.current);
      stallTimer.current = setTimeout(() => {
        if (!abort.signal.aborted) connect();
      }, stallMs);
    };
    const scheduleReconnect = () => {
      if (abort.signal.aborted) return;
      setState("connecting");
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    void (async () => {
      try {
        const response = await fetch(new URL(`${API_BASE}${STREAM_PATH}`, window.location.origin), {
          headers: { Authorization: `Bearer ${tokenRef.current}` },
          signal: abort.signal,
        });
        if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);
        const frames = new MjpegFrames(
          boundaryFromContentType(response.headers.get("content-type") ?? ""),
        );
        const reader = response.body.getReader();
        armStallTimer();
        for (;;) {
          const { value, done } = await reader.read();
          if (done || abort.signal.aborted) break;
          for (const frame of frames.feed(value)) {
            armStallTimer();
            if (busy.current) pending.current = frame;
            else display(frame);
          }
        }
      } catch {
        // Network failure, bad status or malformed stream: handled by the retry below.
      }
      if (stallTimer.current) clearTimeout(stallTimer.current);
      scheduleReconnect();
    })();
  }, [display, setState, stallMs]);

  useEffect(() => {
    tokenRef.current = accessToken;
    if (pendingConnect.current && accessToken) connect();
  }, [accessToken, connect]);

  // Ask the backend whether a camera is configured, then open the stream.
  useEffect(() => {
    let cancelled = false;
    authFetch<CameraStatus>(CAMERA_STATUS_PATH)
      .then((status) => {
        if (cancelled) return;
        onStatusRef.current?.(status);
        if (status.configured) connect();
        else setState("unconfigured");
      })
      .catch(() => {
        // Status unknown (network hiccup): try the stream anyway, it will retry on error.
        if (!cancelled) connect();
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, connect, setState]);

  // Release the connection, the timers and the last frame on unmount.
  useEffect(() => {
    return () => {
      controller.current?.abort();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (stallTimer.current) clearTimeout(stallTimer.current);
      if (shownUrl.current) URL.revokeObjectURL(shownUrl.current);
    };
  }, []);

  const onFrameDone = () => {
    if (shownUrl.current && shownUrl.current !== src) URL.revokeObjectURL(shownUrl.current);
    shownUrl.current = src;
    busy.current = false;
    const next = pending.current;
    pending.current = null;
    if (next) display(next);
  };

  if (state === "unconfigured") return null;

  return (
    <div className={cn("relative bg-black", className)}>
      {src && (
        <img
          ref={(element) => {
            if (element) lastImg.current = element;
            if (imageRef) imageRef.current = element;
          }}
          src={src}
          alt="Flux vidéo de la caméra"
          className="absolute inset-0 h-full w-full object-contain"
          onLoad={() => {
            setState("live");
            onFrameDone();
          }}
          onError={onFrameDone}
        />
      )}
      {state !== "live" && (
        <p
          role="status"
          className="absolute inset-0 grid place-items-center text-sm text-neutral-400"
        >
          Connexion à la caméra…
        </p>
      )}
    </div>
  );
}
