"""Cycle 30.1 — hardening tests: atomic approvals, origin policy,
context revocation, session integrity."""
from __future__ import annotations

import threading

import pytest

from conftest import _req
from forge_agent_bridge.adapter import BridgeError
from forge_agent_bridge.approvals import ApprovalStore
from forge_agent_bridge.context import ContextStore, ProductAgentSessionContext
from forge_agent_bridge.local_bridge import _ALLOWED_HOSTS


def test_concurrent_approval_consumption():
    """Two racing consumes: exactly one may succeed (§3.4)."""
    store = ApprovalStore()
    ap = store.request(session_id="s1", actor="alice", resource="r",
                       action="restore", args={"path": "/tmp/x"})
    token = store.resolve(ap["approval_id"], approved=True,
                          actor="owner")["approval_token"]

    results: list[str] = []
    barrier = threading.Barrier(2)

    def consume(tag: str) -> None:
        barrier.wait()
        try:
            store.consume(token, session_id="s1", resource="r",
                          action="restore", args={"path": "/tmp/x"},
                          actor="alice")
            results.append(f"{tag}:ok")
        except Exception as e:  # noqa: BLE001 — asserting denial
            results.append(f"{tag}:{e}")

    t1 = threading.Thread(target=consume, args=("a",))
    t2 = threading.Thread(target=consume, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len([r for r in results if r.endswith(":ok")]) == 1, results


def test_approval_actor_binding():
    store = ApprovalStore()
    ap = store.request(session_id="s1", actor="alice", resource="r",
                       action="op", args={"a": 1})
    token = store.resolve(ap["approval_id"], approved=True,
                          actor="owner")["approval_token"]
    with pytest.raises(BridgeError):
        store.consume(token, session_id="s1", resource="r", action="op",
                      args={"a": 1}, actor="mallory")
    ok = store.consume(token, session_id="s1", resource="r", action="op",
                       args={"a": 1}, actor="alice")
    assert ok["consumed"] is True


def test_origin_policy(srv):
    """Scheme + host + port checked; malformed/external rejected (§3.5)."""
    from urllib.parse import urlparse

    def check(origin: str | None) -> bool:
        if not origin:
            return True
        try:
            p = urlparse(origin)
        except ValueError:
            return False
        if p.scheme not in {"http", "https"}:
            return False
        if not p.hostname or p.hostname not in _ALLOWED_HOSTS:
            return False
        return p.port is None or 0 < p.port < 65536

    assert check("http://127.0.0.1:4200") is True
    assert check("http://localhost:8080") is True
    assert check("https://127.0.0.1") is True
    assert check("http://evil.example.com:4200") is False
    assert check("javascript:alert(1)") is False
    assert check("file:///etc/passwd") is False
    assert check("http://127.0.0.1.evil.com") is False
    assert check(None) is True


def test_context_revocation_blocks(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    st, _ = _req(port, tok, "POST", "/context/attach",
                 {"session_id": sid, "context": {
                     "identity": "tester", "product_id": "p1",
                     "allowed_tools": ["chat"]}})
    assert st == 200
    st, body = _req(port, tok, "POST", "/context/revoke",
                    {"session_id": sid})
    assert st == 200 and body["revoked"] is True

    store = ContextStore()
    with pytest.raises(BridgeError, match="revoked"):
        store.assert_allowed(sid)


def test_restricted_tool_denied_by_default(tmp_path):
    store = ContextStore(path=tmp_path)
    store.bind("s9", ProductAgentSessionContext(identity="t"))
    with pytest.raises(BridgeError, match="explicit grant"):
        store.assert_allowed("s9", tool="files:write")
    store.assert_allowed("s9", tool="chat")
    store.bind("s9", ProductAgentSessionContext(
        identity="t", allowed_tools=["files:write"]))
    store.assert_allowed("s9", tool="files:write")


def test_require_context_policy(tmp_path):
    store = ContextStore(path=tmp_path)
    store.assert_allowed("unbound")
    with pytest.raises(BridgeError, match="bound product context"):
        store.assert_allowed("unbound", require_context=True)


def test_integrity_endpoint(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt", {"text": "hi"})
    st, body = _req(port, tok, "GET", f"/intel/{sid}/integrity")
    assert st == 200
    assert body["schema"] == "forge/SessionIntegrity/v1"
    assert body["session_id"] == sid
    assert body["event_count"] > 0
    assert body["verdict"] in {"ok", "warnings", "integrity-issues"}
