import { render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it } from "vitest";
import { DetectionOverlay } from "./detection-overlay";
import type { DetectionSnapshot } from "./vision-api";

/** A 640x480 source frame (JSDOM does no real layout, so natural size and the rendered box are
 * both set by hand) rendered, letterboxed, into an 800x300 element. */
function renderOverlay(snapshot: DetectionSnapshot | null) {
  const imageRef = createRef<HTMLImageElement>();
  const utils = render(
    <>
      <img ref={imageRef} alt="" />
      <DetectionOverlay snapshot={snapshot} imageRef={imageRef} />
    </>,
  );
  const image = imageRef.current!;
  Object.defineProperty(image, "naturalWidth", { value: 640, configurable: true });
  Object.defineProperty(image, "naturalHeight", { value: 480, configurable: true });
  image.getBoundingClientRect = () => ({ width: 800, height: 300, left: 0, top: 0 }) as DOMRect;
  // The overlay only recomputes when `snapshot` changes identity (as a fresh WS message would);
  // pass an equivalent-but-new object so the re-render actually re-triggers the effect now that
  // the image has a natural size and a rendered box.
  utils.rerender(
    <>
      <img ref={imageRef} alt="" />
      <DetectionOverlay snapshot={snapshot ? { ...snapshot } : null} imageRef={imageRef} />
    </>,
  );
  return utils;
}

const SNAPSHOT: DetectionSnapshot = {
  analyzed_at: "2026-10-06T12:00:00Z",
  has_intruder: true,
  people: [
    {
      box: { x: 100, y: 50, width: 50, height: 100 },
      confidence: 0.9,
      identity: null,
      identity_confidence: null,
      is_intruder: true,
    },
  ],
};

describe("DetectionOverlay", () => {
  it("renders nothing without a snapshot", () => {
    renderOverlay(null);
    expect(screen.queryByText("INTRUS")).not.toBeInTheDocument();
  });

  it("scales a box from source pixels to the letterboxed display area", () => {
    renderOverlay(SNAPSHOT);
    const label = screen.getByText("INTRUS");
    const box = label.parentElement!;
    // scale = min(800/640, 300/480) = 0.625
    // offsetX = (800 - 640*0.625) / 2 = 200; offsetY = (300 - 480*0.625) / 2 = 0
    expect(box.style.left).toBe("262.5px"); // 200 + 100 * 0.625
    expect(box.style.top).toBe("31.25px"); // 0 + 50 * 0.625
    expect(box.style.width).toBe("31.25px"); // 50 * 0.625
    expect(box.style.height).toBe("62.5px"); // 100 * 0.625
  });

  it("labels a whitelisted person by name instead of INTRUS", () => {
    renderOverlay({
      ...SNAPSHOT,
      has_intruder: false,
      people: [{ ...SNAPSHOT.people[0]!, identity: "kevan", identity_confidence: 0.9 }],
    });
    expect(screen.getByText("kevan")).toBeInTheDocument();
    expect(screen.queryByText("INTRUS")).not.toBeInTheDocument();
  });
});
