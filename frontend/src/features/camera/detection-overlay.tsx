import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import type { DetectionSnapshot } from "./vision-api";

type Props = {
  snapshot: DetectionSnapshot | null;
  /** The <img> showing the live stream: boxes are in its natural (source) pixel space. */
  imageRef: React.RefObject<HTMLImageElement | null>;
};

type Rect = { left: number; top: number; width: number; height: number };

/** Room the name label needs above a box (`-top-6` = 24px). */
const LABEL_HEIGHT_PX = 24;

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
type OverlayPerson = { identity: string | null; blacklistedAs: string | null };

export function DetectionOverlay({ snapshot, imageRef }: Props) {
  const [rects, setRects] = useState<(Rect & OverlayPerson)[]>([]);

  useEffect(() => {
    const image = imageRef.current;
    if (!snapshot || !image) {
      setRects([]);
      return;
    }

    const recompute = () => {
      // The stream swaps the <img> source ~10 times a second, and the size reads 0 while a frame
      // decodes: keep the current boxes and measure again once that frame is in.
      if (!image.naturalWidth || !image.naturalHeight) {
        image.addEventListener("load", recompute, { once: true });
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
          blacklistedAs: person.blacklisted_as,
        })),
      );
    };

    recompute();
    // Re-measure on resize: the container (and so the image's rendered box) can change size.
    window.addEventListener("resize", recompute);
    return () => {
      window.removeEventListener("resize", recompute);
      image.removeEventListener("load", recompute);
    };
  }, [snapshot, imageRef]);

  if (rects.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {rects.map((rect, index) => {
        const isBlacklisted = rect.blacklistedAs !== null;
        const isIntruder = rect.identity === null;
        // Blacklisted outranks the plain intruder/known colouring: it is the one state that
        // must stand out even for someone otherwise whitelisted.
        const color = isBlacklisted ? "violet" : isIntruder ? "red" : "emerald";
        const label = isBlacklisted
          ? `MÉCHANT : ${rect.blacklistedAs}`
          : isIntruder
            ? "INTRUS"
            : rect.identity;
        return (
          <div
            key={index}
            className={cn(
              "absolute rounded-sm border-2",
              color === "violet" && "border-violet-500",
              color === "red" && "border-red-500",
              color === "emerald" && "border-emerald-500",
            )}
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
          >
            <span
              className={cn(
                "absolute left-0 rounded px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap text-white",
                // Above the box, or inside it when the box touches the top edge (clipped otherwise).
                rect.top < LABEL_HEIGHT_PX ? "top-0" : "-top-6",
                color === "violet" && "bg-violet-500",
                color === "red" && "bg-red-500",
                color === "emerald" && "bg-emerald-500",
              )}
            >
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
