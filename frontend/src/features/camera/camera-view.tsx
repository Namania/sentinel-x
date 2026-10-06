import { Maximize, Minimize, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { viewersLabel } from "./camera-api";
import { CameraStream, type StreamState } from "./camera-stream";
import { DetectionOverlay } from "./detection-overlay";
import { useVisionStream } from "./use-vision-stream";

const IDLE_DELAY_MS = 2500;

export function CameraView() {
  const [state, setState] = useState<StreamState>("checking");
  const [otherViewers, setOtherViewers] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [idle, setIdle] = useState(false);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const snapshot = useVisionStream(state === "live");

  useEffect(() => {
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, []);

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
      onDoubleClick={toggleFullscreen}
      className={cn("relative flex flex-1 bg-black", idle && "cursor-none")}
    >
      <CameraStream
        className="flex-1"
        onStateChange={setState}
        onStatus={(status) => setOtherViewers(status.viewers)}
        imageRef={imgRef}
      />
      {state === "live" && <DetectionOverlay snapshot={snapshot} imageRef={imgRef} />}
      {snapshot?.has_intruder && (
        <div className="absolute inset-x-0 top-0 flex justify-center p-3">
          <Badge className="gap-1.5 bg-red-600 text-white">
            <ShieldAlert className="size-4" />
            INTRUS DÉTECTÉ
          </Badge>
        </div>
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
          <span className="text-xs text-neutral-300">{viewersLabel(viewers)}</span>
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
