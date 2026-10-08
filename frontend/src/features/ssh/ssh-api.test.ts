import { describe, expect, it } from "vitest";
import { makeSshEvent, SSH_NOW_MS, sshEventsFixture } from "@/test/ssh";
import {
  describeEvent,
  identityLabel,
  prepend,
  shortFingerprint,
  sshEventsPath,
  summarizeSsh,
} from "./ssh-api";

describe("ssh api helpers", () => {
  it("builds the list path with the limit", () => {
    expect(sshEventsPath()).toBe("/ssh/events?limit=500");
    expect(sshEventsPath(10)).toBe("/ssh/events?limit=10");
  });

  it("names who connected: key comment, else a short fingerprint, else the user", () => {
    expect(identityLabel(makeSshEvent())).toBe("mael.namania@gmail.com");
    expect(identityLabel(makeSshEvent({ key_comment: null }))).toBe("SHA256:Wqjh…9ls");
    expect(identityLabel(makeSshEvent({ key_comment: null, key_fingerprint: null }))).toBe(
      "sentinel-x",
    );
    expect(shortFingerprint("SHA256:abc")).toBe("SHA256:abc");
  });

  it("describes accepted and refused connections", () => {
    expect(describeEvent(makeSshEvent())).toBe("mael.namania@gmail.com depuis 192.168.0.18 · clé");
    expect(describeEvent(makeSshEvent({ method: "password" }))).toBe(
      "mael.namania@gmail.com depuis 192.168.0.18 · mot de passe",
    );
    expect(describeEvent(makeSshEvent({ method: null }))).toBe(
      "mael.namania@gmail.com depuis 192.168.0.18",
    );
    const refused = sshEventsFixture()[1];
    expect(describeEvent(refused)).toBe("root depuis 203.0.113.5 · clé non acceptée");
    expect(describeEvent({ ...refused, reason: "unknown_user" })).toBe(
      "root depuis 203.0.113.5 · utilisateur inconnu",
    );
    expect(describeEvent({ ...refused, reason: "bad_password" })).toBe(
      "root depuis 203.0.113.5 · mot de passe refusé",
    );
    expect(describeEvent({ ...refused, reason: "too_many_attempts" })).toBe(
      "root depuis 203.0.113.5 · trop de tentatives",
    );
  });

  it("prepends newest first, deduplicates by id and caps the list", () => {
    const list = sshEventsFixture();
    const newer = makeSshEvent({ id: "new", occurred_at: new Date(SSH_NOW_MS).toISOString() });
    expect(prepend(list, newer).map((e) => e.id)).toEqual(["new", "ssh-1", "ssh-refused"]);
    expect(prepend(list, { ...list[0], username: "x" }).map((e) => e.id)).toEqual([
      "ssh-1",
      "ssh-refused",
    ]);
    const many = Array.from({ length: 500 }, (_, i) => makeSshEvent({ id: `e${i}` }));
    expect(prepend(many, newer)).toHaveLength(500);
    expect(prepend(many, newer)[0].id).toBe("new");
  });

  it("summarises the last 24 hours and the last accepted connection", () => {
    const old = makeSshEvent({
      id: "old",
      occurred_at: new Date(SSH_NOW_MS - 30 * 3_600_000).toISOString(),
    });
    const summary = summarizeSsh([...sshEventsFixture(), old], SSH_NOW_MS);
    expect(summary).toEqual({ accepted24h: 1, refused24h: 1, lastAccepted: sshEventsFixture()[0] });
    expect(summarizeSsh([], SSH_NOW_MS).lastAccepted).toBeNull();
  });
});
