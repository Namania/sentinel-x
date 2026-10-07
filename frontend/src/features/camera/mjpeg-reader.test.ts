import { describe, expect, it } from "vitest";
import { boundaryFromContentType, MjpegFrames } from "./mjpeg-reader";

const enc = new TextEncoder();
const part = (boundary: string, body: string, extra = "") =>
  enc.encode(
    `--${boundary}\r\nContent-Type: image/jpeg\r\n${extra}Content-Length: ${body.length}\r\n\r\n${body}\r\n`,
  );
const text = (bytes: Uint8Array) => new TextDecoder().decode(bytes);

describe("boundaryFromContentType", () => {
  it("reads the boundary with or without quotes", () => {
    expect(boundaryFromContentType('multipart/x-mixed-replace; boundary="frame"')).toBe("frame");
    expect(boundaryFromContentType("multipart/x-mixed-replace;boundary=boundarydonotcross")).toBe(
      "boundarydonotcross",
    );
    expect(() => boundaryFromContentType("image/jpeg")).toThrow(/boundary/);
  });
});

describe("MjpegFrames", () => {
  it("returns complete frames whatever the chunking", () => {
    const frames = new MjpegFrames("frame");
    const bytes = new Uint8Array([...part("frame", "AAAA"), ...part("frame", "BBBBBB")]);
    const out: Uint8Array[] = [];
    for (let i = 0; i < bytes.length; i += 7) out.push(...frames.feed(bytes.slice(i, i + 7)));
    expect(out.map(text)).toEqual(["AAAA", "BBBBBB"]);
  });

  it("ignores extra part headers such as µStreamer's X-Timestamp", () => {
    const frames = new MjpegFrames("boundarydonotcross");
    const out = frames.feed(part("boundarydonotcross", "JPEGDATA", "X-Timestamp: 1.5\r\n"));
    expect(out.map(text)).toEqual(["JPEGDATA"]);
  });

  it("keeps frame bytes that look like a boundary intact", () => {
    const frames = new MjpegFrames("frame");
    const tricky = "xx--frame\r\nyy";
    expect(frames.feed(part("frame", tricky)).map(text)).toEqual([tricky]);
  });

  it("drops bytes without Content-Length instead of looping forever", () => {
    const frames = new MjpegFrames("frame");
    const bad = enc.encode("--frame\r\nContent-Type: image/jpeg\r\n\r\nZZZZ\r\n");
    expect(() => frames.feed(bad)).toThrow(/Content-Length/);
  });
});
