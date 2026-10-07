/** Incremental parser for a `multipart/x-mixed-replace` (MJPEG) byte stream, mirror of the API's. */

const HEADER_END = new Uint8Array([13, 10, 13, 10]); // \r\n\r\n
const decoder = new TextDecoder();

export function boundaryFromContentType(contentType: string): string {
  const match = /boundary="?([^";]+)"?/i.exec(contentType);
  if (!match) throw new Error(`no multipart boundary in content-type ${contentType}`);
  return match[1]!;
}

function indexOf(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
  outer: for (let i = from; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (haystack[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  if (a.length === 0) return b;
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/**
 * Feed it raw bytes in any chunking; it returns the complete JPEG frames found so far. Every part
 * must carry a `Content-Length` header (µStreamer and the API relay always do), which lets frames
 * contain boundary-like bytes without being cut.
 */
export class MjpegFrames {
  private readonly delimiter: Uint8Array;
  private buffer: Uint8Array = new Uint8Array(0);
  private expected: number | null = null;

  constructor(boundary: string) {
    this.delimiter = new TextEncoder().encode(`--${boundary}`);
  }

  feed(chunk: Uint8Array): Uint8Array[] {
    this.buffer = concat(this.buffer, chunk);
    const frames: Uint8Array[] = [];
    for (;;) {
      if (this.expected === null && !this.readPartHeaders()) break;
      const length = this.expected!;
      if (this.buffer.length < length) break;
      frames.push(this.buffer.slice(0, length));
      this.buffer = this.buffer.slice(length);
      this.expected = null;
    }
    return frames;
  }

  /** Consume up to the end of the next part's headers; false when the buffer lacks them. */
  private readPartHeaders(): boolean {
    const start = indexOf(this.buffer, this.delimiter);
    if (start === -1) {
      // Keep only a tail long enough to hold a split delimiter.
      const keep = this.delimiter.length - 1;
      if (this.buffer.length > keep) this.buffer = this.buffer.slice(-keep);
      return false;
    }
    const headerEnd = indexOf(this.buffer, HEADER_END, start);
    if (headerEnd === -1) return false;
    const headers = decoder.decode(this.buffer.slice(start + this.delimiter.length, headerEnd));
    this.expected = contentLength(headers);
    this.buffer = this.buffer.slice(headerEnd + HEADER_END.length);
    return true;
  }
}

function contentLength(headers: string): number {
  for (const line of headers.split("\r\n")) {
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    if (line.slice(0, colon).trim().toLowerCase() === "content-length") {
      return Number.parseInt(line.slice(colon + 1).trim(), 10);
    }
  }
  throw new Error("multipart part without Content-Length header");
}
