import { describe, expect, it } from "vitest";
import { TEST_USER, VALID_PASSWORD, VALID_REFRESH } from "@/test/server";
import { ApiError } from "@/lib/api";
import { login, me, refresh } from "./auth-api";

describe("auth api", () => {
  it("logs in with email and password", async () => {
    const pair = await login(TEST_USER.email, VALID_PASSWORD);
    expect(pair.refresh_token).toBe(VALID_REFRESH);
    expect(pair.access_token.split(".")).toHaveLength(3);
  });

  it("rejects wrong credentials with a 401 ApiError", async () => {
    const error = await login(TEST_USER.email, "wrong").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
  });

  it("refreshes a session and loads the current user", async () => {
    const pair = await refresh(VALID_REFRESH);
    expect(await me(pair.access_token)).toEqual(TEST_USER);
  });
});
