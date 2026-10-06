import { useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { CameraStream, type StreamState } from "./camera-stream";

/** Wall-screen card: the live stream in a 16:9 frame; the whole card opens the camera page. */
export function CameraCard({ className }: { className?: string }) {
  const [state, setState] = useState<StreamState>("checking");
  return (
    <Link
      to="/camera"
      aria-label="Caméra, voir en grand"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full gap-2 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-0">
          <CardTitle className="text-sm font-medium">Caméra</CardTitle>
          {state === "live" && (
            <Badge className="bg-red-600 text-white">
              <span className="mr-1 inline-block size-2 animate-pulse rounded-full bg-white" />
              EN DIRECT
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {state === "unconfigured" ? (
            <p className="text-muted-foreground grid aspect-video place-items-center text-sm">
              Aucune caméra configurée
            </p>
          ) : (
            <CameraStream
              className="aspect-video overflow-hidden rounded-lg"
              onStateChange={setState}
            />
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
