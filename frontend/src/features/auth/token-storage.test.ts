import { afterEach, describe, expect, it, vi } from "vitest";
import { REFRESH_TOKEN_KEY, readRefreshToken, writeRefreshToken } from "./token-storage";

describe("token storage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("stores and reads the refresh token", () => {
    writeRefreshToken("abc");
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe("abc");
    expect(readRefreshToken()).toBe("abc");
  });

  it("clears it with null", () => {
    writeRefreshToken("abc");
    writeRefreshToken(null);
    expect(readRefreshToken()).toBeNull();
  });

  it("treats a throwing storage as empty", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => writeRefreshToken("abc")).not.toThrow();
    expect(readRefreshToken()).toBeNull();
  });
});
