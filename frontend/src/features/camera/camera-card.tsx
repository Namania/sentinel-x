import { ShieldAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { CameraStream, type StreamState } from "./camera-stream";
import { DetectionOverlay } from "./detection-overlay";
import { useVisionStream } from "./use-vision-stream";

/** Wall-screen card: the live stream in a 16:9 frame; the whole card opens the camera page. */
export function CameraCard({ className }: { className?: string }) {
  const [state, setState] = useState<StreamState>("checking");
  const imgRef = useRef<HTMLImageElement | null>(null);
  const snapshot = useVisionStream(state === "live");
  return (
    <Link
      to="/camera"
      aria-label="Caméra, voir en grand"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full gap-2 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-0">
          <CardTitle className="text-sm font-medium">Caméra</CardTitle>
          <div className="flex items-center gap-2">
            {snapshot?.has_intruder && (
              <Badge className="gap-1 bg-red-600 text-white">
                <ShieldAlert className="size-3.5" />
                INTRUS
              </Badge>
            )}
            {state === "live" && (
              <Badge className="bg-red-600 text-white">
                <span className="mr-1 inline-block size-2 animate-pulse rounded-full bg-white" />
                EN DIRECT
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {state === "unconfigured" ? (
            <p className="text-muted-foreground grid aspect-video place-items-center text-sm">
              Aucune caméra configurée
            </p>
          ) : (
            <div className="relative overflow-hidden rounded-lg">
              <CameraStream className="aspect-video" onStateChange={setState} imageRef={imgRef} />
              {state === "live" && <DetectionOverlay snapshot={snapshot} imageRef={imgRef} />}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
