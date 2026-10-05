import { expect, it } from "vitest";
import { streamUrl } from "./camera-api";

it("builds the relayed stream url with an encoded token and a cache buster", () => {
  const url = streamUrl("a.b/c+d", 3);
  expect(url.startsWith("/api/camera/stream?token=a.b%2Fc%2Bd&t=")).toBe(true);
  expect(url).toMatch(/&t=\d+-3$/);
});
