import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import type { DetectionSnapshot } from "./vision-api";

type Props = {
  snapshot: DetectionSnapshot | null;
  /** The <img> showing the live stream: boxes are in its natural (source) pixel space. */
  imageRef: React.RefObject<HTMLImageElement | null>;
};

type Rect = { left: number; top: number; width: number; height: number };

/** How the source frame (object-contain) maps onto the element's rendered box. */
function containLayout(container: DOMRect, naturalWidth: number, naturalHeight: number) {
  const scale = Math.min(container.width / naturalWidth, container.height / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  return {
    scale,
    offsetX: (container.width - width) / 2,
    offsetY: (container.height - height) / 2,
  };
}

/** Bounding boxes from the vision worker, scaled onto the displayed (object-contain) image. */
export function DetectionOverlay({ snapshot, imageRef }: Props) {
  const [rects, setRects] = useState<(Rect & { identity: string | null })[]>([]);

  useEffect(() => {
    const image = imageRef.current;
    if (!snapshot || !image) {
      setRects([]);
      return;
    }

    const recompute = () => {
      if (!image.naturalWidth || !image.naturalHeight) {
        setRects([]);
        return;
      }
      const { scale, offsetX, offsetY } = containLayout(
        image.getBoundingClientRect(),
        image.naturalWidth,
        image.naturalHeight,
      );
      setRects(
        snapshot.people.map((person) => ({
          left: offsetX + person.box.x * scale,
          top: offsetY + person.box.y * scale,
          width: person.box.width * scale,
          height: person.box.height * scale,
          identity: person.identity,
        })),
      );
    };

    recompute();
    // Re-measure on resize: the container (and so the image's rendered box) can change size.
    window.addEventListener("resize", recompute);
    return () => window.removeEventListener("resize", recompute);
  }, [snapshot, imageRef]);

  if (rects.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {rects.map((rect, index) => {
        const isIntruder = rect.identity === null;
        return (
          <div
            key={index}
            className={cn(
              "absolute rounded-sm border-2",
              isIntruder ? "border-red-500" : "border-emerald-500",
            )}
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
          >
            <span
              className={cn(
                "absolute -top-6 left-0 rounded px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap text-white",
                isIntruder ? "bg-red-500" : "bg-emerald-500",
              )}
            >
              {isIntruder ? "INTRUS" : rect.identity}
            </span>
          </div>
        );
      })}
    </div>
  );
}
