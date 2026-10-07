import { expect, it } from "vitest";
import { viewersLabel } from "./camera-api";

it("agrees the viewer count in French", () => {
  expect(viewersLabel(0)).toBe("0 spectateur");
  expect(viewersLabel(1)).toBe("1 spectateur");
  expect(viewersLabel(3)).toBe("3 spectateurs");
});
