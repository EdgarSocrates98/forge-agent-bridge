"""Cycle 26 — capability matrix vocabulary + SSE streaming (§26.1, §26.6)."""

from __future__ import annotations

import http.client
import socket
import time

from conftest import _req


def _sse_read(port: int, tok: str, path: str, seconds: float = 3.0) -> str:
    """Open the SSE endpoint, read for `seconds`, return raw text."""
    s = socket.create_connection(("127.0.0.1", port), timeout=seconds + 5)
    req = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
           f"Authorization: Bearer {tok}\r\nAccept: text/event-stream\r\n\r\n")
    s.sendall(req.encode())
    s.settimeout(0.5)
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        except TimeoutError:
            continue
    s.close()
    return buf.decode("utf-8", "replace")


def test_capability_matrix_vocabulary(srv) -> None:
    port, tok = srv
    status, body = _req(port, tok, "GET", "/providers")
    assert status == 200
    vocab = {"chat", "streaming", "session-resume", "cancel", "tool-calling",
             "mcp", "files", "approvals", "images", "models", "subagents",
             "plans", "usage", "cloud-handoff"}
    states = {"supported", "unsupported", "experimental",
              "requires-configuration", "requires-authentication",
              "unverified", "error"}
    for p in body["items"]:
        assert p["matrix_version"] == "forge/ProviderCapabilityMatrix/1"
        names = {c["name"] for c in p["capabilities"]}
        assert names == vocab, f"{p['id']}: {vocab - names}"
        for c in p["capabilities"]:
            assert c["state"] in states


def test_capability_states_honest(srv) -> None:
    """No provider claims unverified-by-detection features as supported."""
    port, tok = srv
    _, body = _req(port, tok, "GET", "/providers")
    real = [p for p in body["items"] if p["id"] != "fake"]
    for p in real:
        for c in p["capabilities"]:
            # resume/subagents not live-homologated must not read supported
            if c["name"] in ("subagents", "session-resume"):
                # devin session-resume IS live-homologated (2026-10-30):
                # ACP session/load + adapter impl + transcript in
                # docs/audits/evidence/devin_acp_20261030T093504.jsonl
                if p["id"] == "devin" and c["name"] == "session-resume":
                    assert c["state"] == "supported"
                    continue
                assert c["state"] in {"unverified", "unsupported",
                                      "requires-authentication"}, \
                    f"{p['id']}.{c['name']}={c['state']}"


def test_sse_stream_replay_and_dedup(srv) -> None:
    port, tok = srv
    _, sess = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = sess["id"]
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"provider": "fake", "text": "hello"})
    assert st == 200
    raw = _sse_read(port, tok, f"/agent-sessions/{sid}/stream?after_seq=0",
                    seconds=2.0)
    assert "200" in raw.split("\r\n")[0]
    assert "data:" in raw
    seqs = [int(line[4:]) for line in raw.splitlines()
            if line.startswith("id: ")]
    assert seqs and seqs == sorted(seqs), f"unordered/dup seqs: {seqs}"
    assert len(seqs) == len(set(seqs)), "duplicate seq in stream"


def test_sse_cursor_resume(srv) -> None:
    port, tok = srv
    _, sess = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = sess["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "first"})
    _, body = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                   {"provider": "fake", "after_seq": 0})
    last = max(e["seq"] for e in body["items"])
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "second"})
    raw = _sse_read(port, tok,
                    f"/agent-sessions/{sid}/stream?after_seq={last}",
                    seconds=2.0)
    seqs = [int(line[4:]) for line in raw.splitlines()
            if line.startswith("id: ")]
    assert all(s > last for s in seqs), "cursor resume replayed old events"


def test_sse_requires_auth(srv) -> None:
    port, _ = srv
    _, sess = _req(port, None, "GET", "/status")
    # create a session with token
    _, sess = _req(port, _tok := srv[1], "POST", "/agent-sessions",
                   {"provider": "fake"})
    sid = sess["id"]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", f"/agent-sessions/{sid}/stream")
    r = c.getresponse(); r.read(); c.close()
    assert r.status == 401
