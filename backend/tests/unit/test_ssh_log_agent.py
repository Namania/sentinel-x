"""The host agent lives outside the API package: load it from scripts/ by path."""

import importlib.util
import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

AGENT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "ssh-log-agent.py"
spec = importlib.util.spec_from_file_location("ssh_log_agent", AGENT_PATH)
assert spec is not None and spec.loader is not None
agent = importlib.util.module_from_spec(spec)
# dataclasses resolve `from __future__` annotations through sys.modules: register it first.
sys.modules["ssh_log_agent"] = agent
spec.loader.exec_module(agent)

ACCEPTED_LINE = (
    "Accepted publickey for sentinel-x from 192.168.0.18 port 49513 ssh2: "
    "ED25519 SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls"
)
KEYGEN_OUTPUT = (
    "4096 SHA256:EfqGKQMTw+nb+BML5rZY5l1jBvXSKm6zQ5kBz/KaFkY mael.namania@gmail.com (RSA)\n"
    "256 SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls claude-audit@mac-namania (ED25519)\n"
    "256 SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA no comment (ED25519)\n"
)
COMMENTS = agent.parse_keygen_output(KEYGEN_OUTPUT)


def entry(message, cursor="s=1;i=7", micros="1791445055412000"):
    return {"MESSAGE": message, "__CURSOR": cursor, "__REALTIME_TIMESTAMP": micros, "_PID": "1"}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            ACCEPTED_LINE,
            {
                "outcome": "accepted",
                "username": "sentinel-x",
                "ip": "192.168.0.18",
                "port": 49513,
                "method": "publickey",
                "key_fingerprint": "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls",
                "reason": None,
            },
        ),
        (
            "Accepted keyboard-interactive/pam for pi from 10.0.0.2 port 1 ssh2",
            {
                "outcome": "accepted",
                "username": "pi",
                "ip": "10.0.0.2",
                "port": 1,
                "method": "keyboard-interactive",
                "key_fingerprint": None,
                "reason": None,
            },
        ),
        (
            "Connection closed by authenticating user root 203.0.113.5 port 51234 [preauth]",
            {
                "outcome": "refused",
                "username": "root",
                "ip": "203.0.113.5",
                "port": 51234,
                "method": None,
                "key_fingerprint": None,
                "reason": "key_rejected",
            },
        ),
        (
            "Connection closed by invalid user admin 203.0.113.5 port 51235 [preauth]",
            {
                "outcome": "refused",
                "username": "admin",
                "ip": "203.0.113.5",
                "port": 51235,
                "method": None,
                "key_fingerprint": None,
                "reason": "unknown_user",
            },
        ),
        (
            "Failed password for invalid user admin from 203.0.113.5 port 51236 ssh2",
            {
                "outcome": "refused",
                "username": "admin",
                "ip": "203.0.113.5",
                "port": 51236,
                "method": "password",
                "key_fingerprint": None,
                "reason": "bad_password",
            },
        ),
        (
            "Failed password for sentinel-x from 203.0.113.5 port 51237 ssh2",
            {
                "outcome": "refused",
                "username": "sentinel-x",
                "ip": "203.0.113.5",
                "port": 51237,
                "method": "password",
                "key_fingerprint": None,
                "reason": "bad_password",
            },
        ),
        (
            "Disconnecting authenticating user root 203.0.113.5 port 51238: "
            "Too many authentication failures [preauth]",
            {
                "outcome": "refused",
                "username": "root",
                "ip": "203.0.113.5",
                "port": 51238,
                "method": None,
                "key_fingerprint": None,
                "reason": "too_many_attempts",
            },
        ),
    ],
)
def test_recognised_lines(message, expected):
    assert agent.parse_message(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "pam_unix(sshd:session): session opened for user sentinel-x(uid=1000) by sentinel-x(uid=0)",
        "pam_unix(sshd:session): session closed for user sentinel-x",
        "Invalid user admin from 203.0.113.5 port 51235",
        "Received disconnect from 192.168.0.18 port 49513:11: disconnected by user",
        "Disconnected from user sentinel-x 192.168.0.18 port 49513",
        "Connection closed by 203.0.113.5 port 44444 [preauth]",
        "banner exchange: Connection from 203.0.113.5 port 44445: invalid format",
        "Unable to negotiate with 203.0.113.5 port 44446: no matching key exchange method found."
        " [preauth]",
        "Server listening on 0.0.0.0 port 26655.",
    ],
)
def test_ignored_lines(message):
    assert agent.parse_message(message) is None


@pytest.mark.parametrize(
    ("message", "username", "reason"),
    [
        ("Connection closed by invalid user  203.0.113.5 port 51235 [preauth]", "", "unknown_user"),
        (
            "Connection closed by invalid user foo bar 203.0.113.5 port 51235 [preauth]",
            "foo bar",
            "unknown_user",
        ),
        (
            "Failed password for invalid user a b from 203.0.113.5 port 51236 ssh2",
            "a b",
            "bad_password",
        ),
        (
            "Connection closed by authenticating user  fe80::1%eth0 port 2 [preauth]",
            "",
            "key_rejected",
        ),
    ],
)
def test_probes_with_empty_or_spaced_usernames_are_still_refusals(message, username, reason):
    parsed = agent.parse_message(message)
    assert parsed is not None
    assert (parsed["username"], parsed["reason"]) == (username, reason)
    assert parsed["ip"].startswith(("203.", "fe80"))


def test_an_empty_username_is_sent_as_a_placeholder():
    e = entry("Connection closed by invalid user  203.0.113.5 port 51235 [preauth]")
    assert agent.event_from_entry(e, {}).username == "?"


def test_event_from_entry_adds_time_cursor_and_the_key_comment():
    event = agent.event_from_entry(entry(ACCEPTED_LINE), COMMENTS)
    assert event.journal_id == "s=1;i=7"
    assert event.occurred_at == "2026-10-08T07:37:35.412Z"
    assert event.key_comment == "claude-audit@mac-namania"
    assert event.outcome == "accepted"


def test_event_from_entry_prefers_the_source_timestamp_and_truncates():
    long_user = "u" * 80
    e = entry(f"Connection closed by invalid user {long_user} 203.0.113.5 port 1 [preauth]")
    e["_SOURCE_REALTIME_TIMESTAMP"] = "1791445056000000"
    event = agent.event_from_entry(e, {})
    assert event.occurred_at == "2026-10-08T07:37:36.000Z"
    assert len(event.username) == 64


def test_unknown_fingerprint_gives_no_comment():
    line = ACCEPTED_LINE.replace("WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls", "Zzzz")
    assert agent.event_from_entry(entry(line), COMMENTS).key_comment is None


def test_binary_message_is_ignored():
    assert agent.event_from_entry(entry([65, 66, 255]), COMMENTS) is None
    assert agent.event_from_entry({"__CURSOR": "x", "__REALTIME_TIMESTAMP": "1"}, COMMENTS) is None


def test_parse_keygen_output_maps_fingerprints_to_comments():
    assert COMMENTS == {
        "SHA256:EfqGKQMTw+nb+BML5rZY5l1jBvXSKm6zQ5kBz/KaFkY": "mael.namania@gmail.com",
        "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls": "claude-audit@mac-namania",
        "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA": None,
    }


def test_authorized_keys_reload_only_when_the_file_changes(tmp_path):
    path = tmp_path / "authorized_keys"
    path.write_text("no-port-forwarding ssh-ed25519 AAAA claude-audit@mac-namania\n")
    calls = []

    class Result:
        stdout = KEYGEN_OUTPUT

    def run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    keys = agent.AuthorizedKeys(path, run=run)
    fingerprint = "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls"
    assert keys.comments()[fingerprint] == "claude-audit@mac-namania"
    keys.comments()
    assert len(calls) == 1 and calls[0][:2] == ["ssh-keygen", "-lf"]
    os.utime(path, (1, 1))  # a different mtime: the file changed
    keys.comments()
    assert len(calls) == 2


def test_missing_authorized_keys_gives_an_empty_map(tmp_path):
    assert agent.AuthorizedKeys(tmp_path / "absent").comments() == {}


def test_refusal_memory_reports_one_refusal_per_connection():
    now = [0.0]
    memory = agent.RefusalMemory(ttl_seconds=120.0, clock=lambda: now[0])
    assert memory.first_time("203.0.113.5", 51234) is True
    assert memory.first_time("203.0.113.5", 51234) is False
    assert memory.first_time("203.0.113.5", 51235) is True
    now[0] = 121.0
    assert memory.first_time("203.0.113.5", 51234) is True  # forgotten after the ttl


class FakeOpener:
    """Scripted HTTP answers: an int is a status, an exception is raised."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer

        class Response:
            status = answer

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        if answer >= 400:
            raise urllib.error.HTTPError(request.full_url, answer, "err", {}, None)  # type: ignore[arg-type]
        return Response()


def sample_event():
    return agent.event_from_entry(entry(ACCEPTED_LINE), COMMENTS)


def test_api_client_posts_json_with_the_device_key():
    opener = FakeOpener([201])
    client = agent.ApiClient("http://127.0.0.1:8080/api", "k3y", opener=opener)
    assert client.post(sample_event()) == 201
    request = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:8080/api/ssh/events"
    assert request.get_header("X-device-key") == "k3y"
    body = json.loads(request.data)
    assert body["key_comment"] == "claude-audit@mac-namania" and body["port"] == 49513


def test_deliver_retries_with_backoff_without_advancing():
    opener = FakeOpener([OSError("refused"), 503, 502, 201])
    sleeps = []
    client = agent.ApiClient("http://x/api", "k", opener=opener)
    assert agent.deliver(client, sample_event(), sleep=sleeps.append) is True
    assert sleeps == [1, 2, 4]
    assert len(opener.requests) == 4


def test_duplicate_is_acknowledged_with_200():
    client = agent.ApiClient("http://x/api", "k", opener=FakeOpener([200]))
    assert agent.deliver(client, sample_event(), sleep=lambda s: None) is True


def test_a_422_drops_the_event_and_a_401_waits_a_minute():
    sleeps = []
    client = agent.ApiClient("http://x/api", "k", opener=FakeOpener([401, 422]))
    assert agent.deliver(client, sample_event(), sleep=sleeps.append) is True
    assert sleeps == [60]


def test_journal_command_resumes_from_the_cursor_or_replays_a_day():
    assert agent.journal_command("ssh", None, "-24h")[-2:] == ["--since", "-24h"]
    assert agent.journal_command("ssh", "s=1;i=7", "-24h")[-2:] == ["--after-cursor", "s=1;i=7"]
    assert agent.journal_command("ssh", None, "-24h")[:3] == ["journalctl", "-u", "ssh"]


def test_handle_entry_sends_one_refusal_per_connection_and_advances_the_cursor(tmp_path):
    opener = FakeOpener([201, 201])
    client = agent.ApiClient("http://x/api", "k", opener=opener)
    cursors = agent.CursorStore(tmp_path / "cursor")
    memory = agent.RefusalMemory(clock=lambda: 0.0)
    keys = agent.AuthorizedKeys(tmp_path / "absent")
    failed = entry("Failed password for root from 203.0.113.5 port 5 ssh2", cursor="c1")
    closed = entry(
        "Connection closed by authenticating user root 203.0.113.5 port 5 [preauth]", cursor="c2"
    )
    noise = entry("pam_unix(sshd:session): session closed for user sentinel-x", cursor="c3")
    assert agent.handle_entry(failed, keys, memory, client, cursors).reason == "bad_password"
    assert agent.handle_entry(closed, keys, memory, client, cursors) is None
    assert agent.handle_entry(noise, keys, memory, client, cursors) is None
    assert len(opener.requests) == 1
    assert cursors.read() == "c3"


def test_config_from_env_requires_the_device_key(tmp_path):
    with pytest.raises(SystemExit):
        agent.config_from_env({"HOME": str(tmp_path)})
    config = agent.config_from_env({"HOME": str(tmp_path), "DEVICE_API_KEY": "k"})
    assert config.api_url == "http://127.0.0.1:8080/api"
    assert config.authorized_keys == tmp_path / ".ssh" / "authorized_keys"
    assert config.state_dir == tmp_path / ".local" / "state" / "sentinel-x"
    assert (config.unit, config.first_run_since) == ("ssh", "-24h")
