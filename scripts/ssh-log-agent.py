#!/usr/bin/env python3
"""Relay the Pi's SSH connections (accepted and refused) from journald to the SENTINEL-X API.

Runs on the host as a systemd user service (make ssh-log-install), standard library only:
  journalctl -u ssh -o json -f  →  parse the sshd lines  →  POST /api/ssh/events (X-Device-Key)
An accepted connection is enriched with the comment of its key in ~/.ssh/authorized_keys (the
mail). The journald cursor is kept on disk so nothing is lost while the API is down.
Design: docs/superpowers/specs/2026-10-08-ssh-access-log-design.md
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("ssh-log-agent")

ACCEPTED = re.compile(
    r"^Accepted (?P<method>[\w-]+)(?:/\S+)? for (?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+)"
    r" ssh2(?:: (?P<keytype>\S+) (?P<fp>SHA256:\S+))?$"
)
REFUSED = (
    (
        re.compile(
            r"^Connection closed by authenticating user (?P<user>.*?) (?P<ip>\S+)"
            r" port (?P<port>\d+) \[preauth\]$"
        ),
        "key_rejected",
        None,
    ),
    (
        re.compile(
            r"^Connection closed by invalid user (?P<user>.*?) (?P<ip>\S+)"
            r" port (?P<port>\d+) \[preauth\]$"
        ),
        "unknown_user",
        None,
    ),
    (
        re.compile(
            r"^Failed password for (?:invalid user )?(?P<user>.*?) from (?P<ip>\S+)"
            r" port (?P<port>\d+) ssh2$"
        ),
        "bad_password",
        "password",
    ),
    (
        re.compile(
            r"^Disconnecting (?:invalid user |authenticating user )?(?P<user>.*?) (?P<ip>\S+)"
            r" port (?P<port>\d+): Too many authentication failures \[preauth\]$"
        ),
        "too_many_attempts",
        None,
    ),
)
KEYGEN_LINE = re.compile(r"^\d+ (?P<fp>SHA256:\S+) (?P<comment>.*) \((?P<type>[A-Z0-9-]+)\)$")
RETRY_DELAYS = (1, 2, 4, 8, 16, 30)
MAX_USERNAME = 64
MAX_IP = 45


@dataclass(frozen=True)
class Event:
    journal_id: str
    occurred_at: str
    outcome: str
    username: str
    ip: str
    port: int
    method: str | None = None
    key_fingerprint: str | None = None
    key_comment: str | None = None
    reason: str | None = None


def parse_message(message: str) -> dict | None:
    """The connection described by one sshd line, or None when the line is not one."""
    m = ACCEPTED.match(message)
    if m:
        return {
            "outcome": "accepted",
            "username": m["user"],
            "ip": m["ip"],
            "port": int(m["port"]),
            "method": m["method"],
            "key_fingerprint": m["fp"],
            "reason": None,
        }
    for pattern, reason, method in REFUSED:
        m = pattern.match(message)
        if m:
            return {
                "outcome": "refused",
                "username": m["user"],
                "ip": m["ip"],
                "port": int(m["port"]),
                "method": method,
                "key_fingerprint": None,
                "reason": reason,
            }
    return None


def _iso(micros: int) -> str:
    moment = datetime.fromtimestamp(micros / 1_000_000, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event_from_entry(entry: dict, comments: Mapping[str, str | None]) -> Event | None:
    """One journald JSON entry → Event, or None (not a connection, or an unreadable message)."""
    message = entry.get("MESSAGE")
    if not isinstance(message, str):
        return None  # journalctl gives a byte array for non-UTF-8 text: a probe, not a login
    fields = parse_message(message)
    if fields is None:
        return None
    micros = int(entry.get("_SOURCE_REALTIME_TIMESTAMP") or entry["__REALTIME_TIMESTAMP"])
    fingerprint = fields["key_fingerprint"]
    return Event(
        journal_id=entry["__CURSOR"],
        occurred_at=_iso(micros),
        outcome=fields["outcome"],
        # Scanners probe empty usernames; the API wants at least one character.
        username=(fields["username"] or "?")[:MAX_USERNAME],
        ip=fields["ip"][:MAX_IP],
        port=fields["port"],
        method=fields["method"],
        key_fingerprint=fingerprint,
        key_comment=comments.get(fingerprint) if fingerprint else None,
        reason=fields["reason"],
    )


def parse_keygen_output(text: str) -> dict[str, str | None]:
    """`ssh-keygen -lf authorized_keys` → {fingerprint: comment}; "no comment" → None."""
    out: dict[str, str | None] = {}
    for line in text.splitlines():
        m = KEYGEN_LINE.match(line.strip())
        if m:
            comment = m["comment"].strip()
            out[m["fp"]] = None if comment in ("", "no comment") else comment
    return out


class AuthorizedKeys:
    """The fingerprint → comment map, reread when the file's mtime changes (make ssh-add)."""

    def __init__(self, path: Path, run: Callable[..., object] = subprocess.run) -> None:
        self._path = path
        self._run = run
        self._mtime: float | None = None
        self._comments: dict[str, str | None] = {}

    def comments(self) -> dict[str, str | None]:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime, self._comments = None, {}
            return {}
        if mtime != self._mtime:
            result = self._run(
                ["ssh-keygen", "-lf", str(self._path)], capture_output=True, text=True, check=False
            )
            self._comments = parse_keygen_output(getattr(result, "stdout", "") or "")
            self._mtime = mtime
        return self._comments


class RefusalMemory:
    """sshd can write two refusal lines for one connection: report the (ip, port) once."""

    def __init__(
        self, ttl_seconds: float = 120.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._seen: dict[tuple[str, int], float] = {}

    def first_time(self, ip: str, port: int) -> bool:
        now = self._clock()
        self._seen = {k: t for k, t in self._seen.items() if now - t < self._ttl}
        key = (ip, port)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True


class ApiClient:
    def __init__(
        self,
        base_url: str,
        device_key: str,
        opener: Callable[..., object] = urllib.request.urlopen,
        timeout: float = 5.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/ssh/events"
        self._key = device_key
        self._opener = opener
        self._timeout = timeout

    def post(self, event: Event) -> int:
        """HTTP status of the API's answer; raises OSError when it cannot be reached."""
        request = urllib.request.Request(
            self._url,
            data=json.dumps(asdict(event)).encode(),
            headers={"Content-Type": "application/json", "X-Device-Key": self._key},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:  # type: ignore[attr-defined]
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return exc.code


def deliver(client: ApiClient, event: Event, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Send until the API has the event (201/200) or refuses it for good (422): then True, the
    cursor may advance. Network errors and 5xx retry with backoff; a wrong device key retries
    every minute (a configuration problem someone must fix)."""
    attempt = 0
    while True:
        try:
            status: int | None = client.post(event)
        except OSError as exc:
            status = None
            log.warning("API unreachable: %s", exc)
        if status in (200, 201):
            return True
        if status == 422:
            log.warning("event refused by the API (422), dropped: %s", asdict(event))
            return True
        if status in (401, 403):
            log.error("device key refused (HTTP %s): check DEVICE_API_KEY; retry in 60 s", status)
            sleep(60)
            continue
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        attempt += 1
        if status is not None:
            log.warning("API answered %s, retrying in %s s", status, delay)
        sleep(delay)


class CursorStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> str | None:
        try:
            return self._path.read_text().strip() or None
        except FileNotFoundError:
            return None

    def write(self, cursor: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(cursor)
        os.replace(tmp, self._path)


def journal_command(unit: str, cursor: str | None, first_run_since: str) -> list[str]:
    cmd = ["journalctl", "-u", unit, "-o", "json", "-f", "--no-pager"]
    return cmd + (["--after-cursor", cursor] if cursor else ["--since", first_run_since])


def handle_entry(
    entry: dict,
    keys: AuthorizedKeys,
    memory: RefusalMemory,
    client: ApiClient,
    cursors: CursorStore,
) -> Event | None:
    """Send the connection this entry describes, if any, then remember the cursor."""
    event = event_from_entry(entry, keys.comments())
    if event is not None and (
        event.outcome == "accepted" or memory.first_time(event.ip, event.port)
    ):
        deliver(client, event)
    else:
        event = None
    cursor = entry.get("__CURSOR")
    if isinstance(cursor, str) and cursor:
        cursors.write(cursor)
    return event


@dataclass(frozen=True)
class Config:
    api_url: str
    device_key: str
    authorized_keys: Path
    state_dir: Path
    unit: str
    first_run_since: str


def config_from_env(env: Mapping[str, str] = os.environ) -> Config:
    key = env.get("DEVICE_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEVICE_API_KEY manquant (make ssh-log-install l'écrit dans ssh-log.env)")
    home = Path(env.get("HOME", str(Path.home())))
    return Config(
        api_url=env.get("SENTINEL_API_URL", "http://127.0.0.1:8080/api"),
        device_key=key,
        authorized_keys=Path(
            env.get("SENTINEL_AUTHORIZED_KEYS", str(home / ".ssh" / "authorized_keys"))
        ),
        state_dir=Path(
            env.get("SENTINEL_STATE_DIR", str(home / ".local" / "state" / "sentinel-x"))
        ),
        unit=env.get("SENTINEL_JOURNAL_UNIT", "ssh"),
        first_run_since=env.get("SENTINEL_FIRST_RUN_SINCE", "-24h"),
    )


def run(config: Config) -> None:
    keys = AuthorizedKeys(config.authorized_keys)
    cursors = CursorStore(config.state_dir / "ssh-log.cursor")
    memory = RefusalMemory()
    client = ApiClient(config.api_url, config.device_key)
    while True:
        cursor = cursors.read()
        cmd = journal_command(config.unit, cursor, config.first_run_since)
        log.info("following %s (%s)", config.unit, "from cursor" if cursor else "last 24 h")
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("unreadable journal line skipped")
                    continue
                event = handle_entry(entry, keys, memory, client, cursors)
                if event is not None:
                    log.info(
                        "%s %s from %s (%s)",
                        event.outcome,
                        event.username,
                        event.ip,
                        event.key_comment or event.reason or event.method,
                    )
        log.warning("journalctl exited (%s); restarting in 5 s", proc.returncode)
        time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        run(config_from_env())
    except KeyboardInterrupt:
        pass
