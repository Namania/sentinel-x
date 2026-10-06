import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { cn } from "@/lib/utils";
import { CAMERA_STATUS_PATH, streamUrl, type CameraStatus } from "./camera-api";

export const RECONNECT_DELAY_MS = 2000;

export type StreamState = "checking" | "unconfigured" | "connecting" | "live";

type Props = {
  onStateChange?: (state: StreamState) => void;
  onStatus?: (status: CameraStatus) => void;
  className?: string;
};

/**
 * The relayed MJPEG stream: asks `/camera/status`, opens `<img>` on the relay, reconnects 2 s
 * after an error, releases the image on unmount. Renders nothing when no camera is configured;
 * the parent decides what to say.
 */
export function CameraStream({ onStateChange, onStatus, className }: Props) {
  const { accessToken, authFetch } = useAuth();
  // The stream keeps the token it was opened with; only a reconnection uses a newer one.
  const tokenRef = useRef(accessToken);
  // Set when the stream should open but the session token has not been committed yet.
  const pendingConnect = useRef(false);
  const [state, setStateRaw] = useState<StreamState>("checking");
  const [src, setSrc] = useState<string | null>(null);
  const attemptRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // React nulls element refs before effect cleanups run, so keep the last <img> ourselves.
  const lastImg = useRef<HTMLImageElement | null>(null);
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

  const connect = useCallback(() => {
    if (!tokenRef.current) {
      pendingConnect.current = true;
      return;
    }
    pendingConnect.current = false;
    attemptRef.current += 1;
    setState("connecting");
    setSrc(streamUrl(tokenRef.current, attemptRef.current));
  }, [setState]);

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

  // Release the camera and the pending timer on unmount.
  useEffect(() => {
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (lastImg.current) lastImg.current.src = "";
    };
  }, []);

  const scheduleReconnect = () => {
    setState("connecting");
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
  };

  if (state === "unconfigured") return null;

  return (
    <div className={cn("relative bg-black", className)}>
      {src && (
        <img
          ref={(element) => {
            if (element) lastImg.current = element;
          }}
          src={src}
          alt="Flux vidéo de la caméra"
          className="absolute inset-0 h-full w-full object-contain"
          onLoad={() => setState("live")}
          onError={scheduleReconnect}
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
