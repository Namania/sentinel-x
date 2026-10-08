import type { SshEvent } from "@/features/ssh/ssh-api";

export const SSH_NOW_MS = Date.UTC(2026, 9, 8, 9, 0, 0);

export function makeSshEvent(overrides: Partial<SshEvent> = {}): SshEvent {
  return {
    id: "ssh-1",
    journal_id: "s=1;i=1",
    occurred_at: new Date(SSH_NOW_MS - 4 * 60_000).toISOString(),
    outcome: "accepted",
    username: "sentinel-x",
    ip: "192.168.0.18",
    port: 49513,
    method: "publickey",
    key_fingerprint: "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls",
    key_comment: "mael.namania@gmail.com",
    reason: null,
    ...overrides,
  };
}

/** Default API state in tests: one accepted connection, one refusal an hour earlier. */
export function sshEventsFixture(): SshEvent[] {
  return [
    makeSshEvent(),
    makeSshEvent({
      id: "ssh-refused",
      journal_id: "s=1;i=0",
      occurred_at: new Date(SSH_NOW_MS - 60 * 60_000).toISOString(),
      outcome: "refused",
      username: "root",
      ip: "203.0.113.5",
      port: 51234,
      method: null,
      key_fingerprint: null,
      key_comment: null,
      reason: "key_rejected",
    }),
  ];
}
