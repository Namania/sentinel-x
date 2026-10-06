import { http, HttpResponse, ws } from "msw";
import { setupServer } from "msw/node";
import { decodeJwtPayload } from "@/features/auth/jwt";
import { accessTokenExpiringIn, makeJwt } from "./jwt";
import { bucketsFixture, DEVICE, makeReading, NOW_MS, readingsFixture } from "./sensors";
import { healthFixture, SERVER_NOW_MS } from "./server-health";

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

const unauthenticated = () => HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });

export const sensorsLink = ws.link("ws://localhost:3000/ws");

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
  http.get("/api/camera/status", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json({ configured: true, viewers: 0 })
      : unauthenticated(),
  ),
  http.get("/api/server/health", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const history = healthFixture(4, SERVER_NOW_MS);
    return HttpResponse.json({ latest: history.at(-1) ?? null, history });
  }),
];

export const server = setupServer(...handlers);
