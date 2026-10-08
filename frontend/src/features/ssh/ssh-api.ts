export type Outcome = "accepted" | "refused";
export type Reason = "key_rejected" | "unknown_user" | "bad_password" | "too_many_attempts";

export type SshEvent = {
  id: string;
  journal_id: string;
  occurred_at: string;
  outcome: Outcome;
  username: string;
  ip: string;
  port: number;
  method: string | null;
  key_fingerprint: string | null;
  key_comment: string | null;
  reason: Reason | null;
};

export const SSH_EVENTS_PATH = "/ssh/events";
/** The API's maximum; the page says so when the history is longer. */
export const SSH_LIMIT = 500;

export function sshEventsPath(limit = SSH_LIMIT): string {
  return `${SSH_EVENTS_PATH}?limit=${limit}`;
}

export const REASON_LABELS: Record<Reason, string> = {
  key_rejected: "clé non acceptée",
  unknown_user: "utilisateur inconnu",
  bad_password: "mot de passe refusé",
  too_many_attempts: "trop de tentatives",
};

export const METHOD_LABELS: Record<string, string> = {
  publickey: "clé",
  password: "mot de passe",
  "keyboard-interactive": "interactif",
};

/** « SHA256:Wqjh…9ls » — enough to tell two keys apart on one line. */
export function shortFingerprint(fingerprint: string): string {
  return fingerprint.length > 16
    ? `${fingerprint.slice(0, 11)}…${fingerprint.slice(-3)}`
    : fingerprint;
}

/** Who connected: the key's comment (the mail), else its fingerprint, else the system user. */
export function identityLabel(event: SshEvent): string {
  if (event.key_comment) return event.key_comment;
  if (event.key_fingerprint) return shortFingerprint(event.key_fingerprint);
  return event.username;
}

/** « mael@… depuis 192.168.0.18 · clé » / « root depuis 203.0.113.5 · clé non acceptée ». */
export function describeEvent(event: SshEvent): string {
  if (event.outcome === "refused") {
    const reason = event.reason ? REASON_LABELS[event.reason] : "refusée";
    return `${event.username} depuis ${event.ip} · ${reason}`;
  }
  const method = event.method ? ` · ${METHOD_LABELS[event.method] ?? event.method}` : "";
  return `${identityLabel(event)} depuis ${event.ip}${method}`;
}

/** Add or replace the event with the same id; newest first, capped at SSH_LIMIT. */
export function prepend(events: SshEvent[], event: SshEvent): SshEvent[] {
  const others = events.filter((e) => e.id !== event.id);
  return [...others, event]
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at))
    .slice(0, SSH_LIMIT);
}

export type SshSummary = {
  accepted24h: number;
  refused24h: number;
  lastAccepted: SshEvent | null;
};

export function summarizeSsh(events: SshEvent[], nowMs: number): SshSummary {
  let accepted24h = 0;
  let refused24h = 0;
  for (const e of events) {
    if (nowMs - Date.parse(e.occurred_at) > 86_400_000) continue;
    if (e.outcome === "accepted") accepted24h += 1;
    else refused24h += 1;
  }
  return {
    accepted24h,
    refused24h,
    lastAccepted: events.find((e) => e.outcome === "accepted") ?? null,
  };
}
