import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { installMatchMedia } from "./match-media";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
  document.documentElement.className = "";
  document.title = "";
});
afterAll(() => server.close());

installMatchMedia(false);
// Radix UI and Recharts rely on ResizeObserver, which jsdom does not implement. The stub reports
// a fixed size at once so charts render their SVG and tests can query marks and labels.
vi.stubGlobal(
  "ResizeObserver",
  class {
    private readonly callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }
    observe(target: Element) {
      const contentRect = {
        width: 600,
        height: 224,
        top: 0,
        left: 0,
        x: 0,
        y: 0,
        bottom: 224,
        right: 600,
        toJSON: () => ({}),
      };
      this.callback(
        [{ target, contentRect } as unknown as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    }
    unobserve() {}
    disconnect() {}
  },
);
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};

// jsdom has no object URLs; the camera stream shows each frame through one.
let objectUrls = 0;
URL.createObjectURL ??= () => `blob:test/${++objectUrls}`;
URL.revokeObjectURL ??= () => {};
