import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useNow } from "./use-now";

describe("useNow", () => {
  afterEach(() => vi.useRealTimers());

  it("rounds down to the step and re-renders exactly at the next boundary", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.UTC(2026, 9, 6, 9, 0, 59, 900)));
    const { result } = renderHook(() => useNow(30_000));
    expect(result.current).toBe(Date.UTC(2026, 9, 6, 9, 0, 30));
    act(() => vi.advanceTimersByTime(100));
    expect(result.current).toBe(Date.UTC(2026, 9, 6, 9, 1, 0));
    act(() => vi.advanceTimersByTime(29_999));
    expect(result.current).toBe(Date.UTC(2026, 9, 6, 9, 1, 0));
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(Date.UTC(2026, 9, 6, 9, 1, 30));
  });
});
