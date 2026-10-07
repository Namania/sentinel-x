import type { SirenState } from "@/features/alerts/siren-api";

export function makeSiren(overrides: Partial<SirenState> = {}): SirenState {
  return { on: false, reason: null, open: 0, muted_until: null, ...overrides };
}
