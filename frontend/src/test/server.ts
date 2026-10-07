import { http, HttpResponse, ws } from "msw";
import { setupServer } from "msw/node";
import { decodeJwtPayload } from "@/features/auth/jwt";
import { alertsFixture } from "./alerts";
import { accessTokenExpiringIn, makeJwt } from "./jwt";
import { bucketsFixture, DEVICE, makeReading, NOW_MS, readingsFixture } from "./sensors";
import { healthFixture, SERVER_NOW_MS } from "./server-health";
import { makeSiren } from "./siren";

export const TEST_USER = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "alice@example.com",
  created_at: "2026-10-05T10:00:00Z",
};
export const VALID_PASSWORD = "secret123";
export const VALID_REFRESH = makeJwt({ sub: TEST_USER.id, type: "refresh", exp: 4_102_444_800 });

export function tokenPair(accessTtlSeconds = 900) {
  return {
    access_token: accessTokenExpiringIn(accessTtlSeconds),
    refresh_token: VALID_REFRESH,
    token_type: "bearer",
  };
}

function bearer(request: Request): string | null {
  return request.headers.get("Authorization")?.replace(/^Bearer /, "") ?? null;
}

function isValidAccessToken(token: string | null): boolean {
  if (!token) return false;
  const payload = decodeJwtPayload(token);
  return (
    payload?.type === "access" && typeof payload.exp === "number" && payload.exp * 1000 > Date.now()
  );
}

// A healthy camera: the frame counter grows between two status calls.
let cameraFrames = 0;

const unauthenticated = () => HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });

export const sensorsLink = ws.link("ws://localhost:3000/ws");

const JPEG_BOUNDARY = "frame";
const encoder = new TextEncoder();

function mjpegPart(frame: Uint8Array): Uint8Array {
  const head = encoder.encode(
    `--${JPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`,
  );
  const out = new Uint8Array(head.length + frame.length + 2);
  out.set(head, 0);
  out.set(frame, head.length);
  out.set([13, 10], head.length + frame.length);
  return out;
}

/** A fake JPEG: the SOI/EOI markers around a label, enough for a Blob. */
export function fakeJpeg(label: string): Uint8Array {
  return new Uint8Array([0xff, 0xd8, ...encoder.encode(label), 0xff, 0xd9]);
}

/**
 * An MJPEG response that sends `frames` `gapMs` apart, then stays open (or closes with `end`).
 * Tests that need control over the timing build their own ReadableStream.
 */
export function mjpegResponse(frames: Uint8Array[], gapMs = 0, end = false) {
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const frame of frames) {
        controller.enqueue(mjpegPart(frame));
        if (gapMs) await new Promise((r) => setTimeout(r, gapMs));
      }
      if (end) controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": `multipart/x-mixed-replace; boundary=${JPEG_BOUNDARY}` },
  });
}

const BUCKET_MS: Record<string, number> = {
  "1m": 60_000,
  "5m": 300_000,
  "15m": 900_000,
  "1h": 3_600_000,
};

export const sensorHandlers = [
  http.get("/api/sensors/devices", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json([{ device_id: DEVICE, last_seen: new Date(NOW_MS).toISOString() }])
      : unauthenticated(),
  ),
  http.get("/api/sensors/latest", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json([makeReading({ recorded_at: new Date(NOW_MS).toISOString() })])
      : unauthenticated(),
  ),
  http.get("/api/sensors/readings", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const bucket = new URL(request.url).searchParams.get("bucket");
    if (bucket) return HttpResponse.json(bucketsFixture(4, NOW_MS, BUCKET_MS[bucket] ?? 60_000));
    return HttpResponse.json(readingsFixture(5, NOW_MS));
  }),
];

/** Mirrors the real backend: login/refresh issue pairs, protected routes need a live access token. */
export const handlers = [
  // Accept WebSocket connections silently; tests that need events add their own listener.
  sensorsLink.addEventListener("connection", () => {}),
  ...sensorHandlers,
  http.get("/api/health", () => HttpResponse.json({ status: "ok" })),
  http.post("/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as { email: string; password: string };
    const email = body.email.trim().toLowerCase();
    if (email === TEST_USER.email && body.password === VALID_PASSWORD) {
      return HttpResponse.json(tokenPair());
    }
    return HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 });
  }),
  http.post("/api/auth/refresh", async ({ request }) => {
    const body = (await request.json()) as { refresh_token: string };
    if (body.refresh_token === VALID_REFRESH) return HttpResponse.json(tokenPair());
    return HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 });
  }),
  http.get("/api/users/me", ({ request }) =>
    isValidAccessToken(bearer(request)) ? HttpResponse.json(TEST_USER) : unauthenticated(),
  ),
  // A live camera: one frame right away, then the connection stays open.
  http.get("/api/camera/stream", ({ request }) =>
    isValidAccessToken(bearer(request)) ? mjpegResponse([fakeJpeg("first")]) : unauthenticated(),
  ),
  http.get("/api/camera/status", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json({ configured: true, viewers: 0, frames: (cameraFrames += 30) })
      : unauthenticated(),
  ),
  http.get("/api/alerts", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const url = new URL(request.url);
    const status = url.searchParams.get("status") ?? "all";
    const device = url.searchParams.get("device_id");
    const limit = Number(url.searchParams.get("limit") ?? 100);
    const rows = alertsFixture()
      .filter((a) => (device ? a.device_id === device : true))
      .filter((a) => status === "all" || (status === "open") === (a.resolved_at === null));
    return HttpResponse.json(rows.slice(0, limit));
  }),
  http.get("/api/alerts/summary", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json({ open: alertsFixture().filter((a) => a.resolved_at === null).length })
      : unauthenticated(),
  ),
  http.get("/api/alerts/siren", ({ request }) =>
    isValidAccessToken(bearer(request)) ? HttpResponse.json(makeSiren()) : unauthenticated(),
  ),
  http.post("/api/alerts/siren/mute", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json(makeSiren({ muted_until: "2026-10-07T07:15:00Z" }))
      : unauthenticated(),
  ),
  http.delete("/api/alerts/siren/mute", ({ request }) =>
    isValidAccessToken(bearer(request)) ? HttpResponse.json(makeSiren()) : unauthenticated(),
  ),
  http.get("/api/server/health", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const history = healthFixture(4, SERVER_NOW_MS);
    return HttpResponse.json({ latest: history.at(-1) ?? null, history });
  }),
];

export const server = setupServer(...handlers);
