import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { decodeJwtPayload } from "@/features/auth/jwt";
import { accessTokenExpiringIn, makeJwt } from "./jwt";

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

/** Mirrors the real backend: login/refresh issue pairs, protected routes need a live access token. */
export const handlers = [
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
];

export const server = setupServer(...handlers);
