import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { ApiError, NetworkError, apiFetch } from "./api";

describe("apiFetch", () => {
  it("prefixes /api, sends JSON and parses the response", async () => {
    server.use(
      http.post("/api/echo", async ({ request }) => {
        return HttpResponse.json({
          contentType: request.headers.get("Content-Type"),
          body: await request.json(),
        });
      }),
    );
    const result = await apiFetch<{ contentType: string; body: unknown }>("/echo", {
      method: "POST",
      body: JSON.stringify({ a: 1 }),
    });
    expect(result).toEqual({ contentType: "application/json", body: { a: 1 } });
  });

  it("sends the bearer token when given", async () => {
    server.use(
      http.get("/api/whoami", ({ request }) =>
        HttpResponse.json({ auth: request.headers.get("Authorization") }),
      ),
    );
    expect(await apiFetch("/whoami", {}, "tok")).toEqual({ auth: "Bearer tok" });
    expect(await apiFetch("/whoami")).toEqual({ auth: null });
  });

  it("throws ApiError with the status and detail", async () => {
    server.use(
      http.get("/api/secret", () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
      ),
    );
    const error = await apiFetch("/secret").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe("Not authenticated");
  });

  it("throws NetworkError when the server is unreachable", async () => {
    server.use(http.get("/api/down", () => HttpResponse.error()));
    await expect(apiFetch("/down")).rejects.toBeInstanceOf(NetworkError);
  });
});
