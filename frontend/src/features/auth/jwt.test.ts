import { describe, expect, it } from "vitest";
import { makeJwt } from "@/test/jwt";
import { decodeJwtPayload, jwtExpiresAt } from "./jwt";

describe("jwt helpers", () => {
  it("reads exp as milliseconds", () => {
    expect(jwtExpiresAt(makeJwt({ exp: 1_800_000_000 }))).toBe(1_800_000_000_000);
  });

  it("returns null without exp", () => {
    expect(jwtExpiresAt(makeJwt({ sub: "x" }))).toBeNull();
  });

  it("returns null for garbage", () => {
    expect(jwtExpiresAt("not-a-token")).toBeNull();
    expect(decodeJwtPayload("a.%%%.c")).toBeNull();
  });

  it("decodes base64url payloads", () => {
    expect(decodeJwtPayload(makeJwt({ type: "access", name: "é?>" }))).toEqual({
      type: "access",
      name: "é?>",
    });
  });
});
