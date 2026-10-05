import { expect, it } from "vitest";
import { initials } from "./initials";

it("uses the first letters of a dotted local part", () => {
  expect(initials("jean.dupont@example.com")).toBe("JD");
  expect(initials("marie-claire_x@example.com")).toBe("MC");
});

it("falls back to the first two letters", () => {
  expect(initials("alice@example.com")).toBe("AL");
  expect(initials("a@example.com")).toBe("A");
});
