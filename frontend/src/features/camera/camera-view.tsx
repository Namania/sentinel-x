import { Maximize, Minimize } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/use-auth";
import { cn } from "@/lib/utils";
import { CAMERA_STATUS_PATH, streamUrl, type CameraStatus } from "./camera-api";

export const RECONNECT_DELAY_MS = 2000;
const IDLE_DELAY_MS = 2500;

type ViewState = "checking" | "unconfigured" | "connecting" | "live";

export function CameraView() {
  const { accessToken, authFetch } = useAuth();
  // The stream keeps the token it was opened with; only a reconnection uses a newer one.
  const tokenRef = useRef(accessToken);
  // Set when the stream should open but the session token has not been committed yet.
  const pendingConnect = useRef(false);

  const [state, setState] = useState<ViewState>("checking");
  const [otherViewers, setOtherViewers] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [idle, setIdle] = useState(false);

  const attemptRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // React nulls element refs before effect cleanups run, so keep the last <img> ourselves.
  const lastImg = useRef<HTMLImageElement | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const connect = useCallback(() => {
    if (!tokenRef.current) {
      pendingConnect.current = true;
      return;
    }
    pendingConnect.current = false;
    attemptRef.current += 1;
    setState("connecting");
    setSrc(streamUrl(tokenRef.current, attemptRef.current));
  }, []);

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
        setOtherViewers(status.viewers);
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
  }, [authFetch, connect]);

  // Release the camera and pending timers on unmount.
  useEffect(() => {
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (idleTimer.current) clearTimeout(idleTimer.current);
      if (lastImg.current) lastImg.current.src = "";
    };
  }, []);

  const scheduleReconnect = () => {
    setState("connecting");
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
  };

  const toggleFullscreen = useCallback(() => {
    const element = containerRef.current;
    if (!element || typeof element.requestFullscreen !== "function") return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void element.requestFullscreen();
  }, []);

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest?.('[role="menu"], input, textarea, [contenteditable="true"]')) return;
      if (target?.isContentEditable) return;
      if (event.key === "f" || event.key === "F") toggleFullscreen();
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("keydown", onKey);
    };
  }, [toggleFullscreen]);

  const wake = () => {
    setIdle(false);
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setIdle(true), IDLE_DELAY_MS);
  };

  if (state === "unconfigured") {
    return (
      <section className="flex flex-1 items-center justify-center p-4 text-center">
        <div className="max-w-md space-y-2">
          <h1 className="text-xl font-semibold">Aucune caméra configurée</h1>
          <p className="text-muted-foreground">
            Renseigne <code>CAMERA_STREAM_URL</code> dans <code>backend/.env</code> puis redémarre
            l'API.
          </p>
        </div>
      </section>
    );
  }

  // iPhone Safari has no element fullscreen: hide the button there.
  const fullscreenSupported = Boolean(document.fullscreenEnabled);
  const viewers = otherViewers + (state === "live" ? 1 : 0);

  return (
    <div
      ref={containerRef}
      onMouseMove={wake}
      onTouchStart={wake}
      onClick={wake}
      className={cn("relative flex flex-1 bg-black", idle && "cursor-none")}
    >
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
          onDoubleClick={toggleFullscreen}
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
      <div
        className={cn(
          "absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent p-4 transition-opacity",
          idle && "pointer-events-none opacity-0",
        )}
      >
        <div className="flex items-center gap-3">
          {state === "live" && (
            <Badge className="bg-red-600 text-white">
              <span className="mr-1 inline-block size-2 animate-pulse rounded-full bg-white" />
              EN DIRECT
            </Badge>
          )}
          <span className="text-xs text-neutral-300">
            {viewers} {viewers > 1 ? "spectateurs" : "spectateur"}
          </span>
        </div>
        {fullscreenSupported && (
          <Button
            variant="ghost"
            size="icon"
            className="text-white hover:bg-white/15 hover:text-white"
            aria-label={fullscreen ? "Quitter le plein écran" : "Plein écran"}
            onClick={(event) => {
              event.stopPropagation();
              toggleFullscreen();
            }}
          >
            {fullscreen ? <Minimize className="size-6" /> : <Maximize className="size-6" />}
          </Button>
        )}
      </div>
    </div>
  );
}
