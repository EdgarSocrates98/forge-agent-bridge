"""Cycle 23 — runners, budgets, collaboration enforcement, handoff."""

from conftest import _req


def _mk_session(port, tok, principal="local"):
    st, s = _req(port, tok, "POST", "/agent-sessions",
                 {"provider": "fake"}, principal)
    assert st == 201
    return s["id"]


def test_runners_lifecycle(srv):
    port, tok = srv
    st, items = _req(port, tok, "GET", "/runners")
    assert st == 200 and any(r["id"] == "local" for r in items["items"])
    st, r = _req(port, tok, "POST", "/runners",
                 {"id": "r1", "kind": "remote"})
    assert st == 201 and r["state"] == "unverified"  # honest — never probed
    # SSRF: unresolvable/blocked endpoints are rejected at registration
    st, _e = _req(port, tok, "POST", "/runners",
                  {"id": "rbad", "kind": "remote",
                   "endpoint": "http://169.254.169.254/"})
    assert st == 422
    st, h = _req(port, tok, "POST", "/runners/r1/health")
    assert h["state"] in ("unverified", "ready")    # real reachability probe
    # remote placement refused without verified health
    st, _e = _req(port, tok, "POST", "/agent-sessions",
                  {"provider": "fake", "runner": "r1"})
    assert st in (422, 502)
    st, d = _req(port, tok, "POST", "/runners/r1/deregister")
    assert d["drained"] is True
    st, _e = _req(port, tok, "POST", "/runners/local/deregister")
    assert st == 422  # local runner is protected


def test_budget_enforcement(srv):
    port, tok = srv
    sid = _mk_session(port, tok)
    st, _ = _req(port, tok, "POST", "/budget/limits",
                 {"scope": "session", "key": sid, "window": "day",
                  "tokens": 5})
    assert st == 201
    # first prompt records fake usage (10 in / 20 out) → exceeds next check
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "hi"})
    assert st == 200
    st, e = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "again"})
    assert st == 429 and e["error"]["code"] == "FAB-BUDGET"


def test_collab_observer_enforcement(srv):
    port, tok = srv
    sid = _mk_session(port, tok, principal="owner1")
    st, rec = _req(port, tok, "POST", f"/agent-sessions/{sid}/share",
                   {"visibility": "team", "observers": ["pm1"]},
                   principal="owner1")
    assert st == 200 and rec["collab"]["visibility"] == "team"
    # observer cannot prompt
    st, e = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "x"}, principal="pm1")
    assert st == 403 and e["error"]["code"] == "FAB-FORBIDDEN"
    # observer CAN read events (read-only preserved)
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                 {}, principal="pm1")
    assert st == 200
    # approval spoofing: non-delegate cannot approve
    st, e = _req(port, tok, "POST", f"/agent-sessions/{sid}/approve",
                 {"approval_id": "a1", "approved": True}, principal="pm1")
    assert st == 403
    # comments are append-only and work for observers
    st, r = _req(port, tok, "POST", f"/agent-sessions/{sid}/comment",
                 {"text": "watching"}, principal="pm1")
    assert st == 200 and r["comments"][0]["author"] == "pm1"


def test_handoff_context_rebuild(srv):
    port, tok = srv
    sid = _mk_session(port, tok)
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt", {"text": "hi"})
    st, r = _req(port, tok, "POST", f"/agent-sessions/{sid}/handoff",
                 {"mode": "context-rebuild"})
    assert st == 201
    assert r["handoff"] == "context-rebuild"
    assert r["continuity"] == "reconstructed"  # honest label, never identical
    assert r["session"]["id"] != sid


def test_audit_trail(srv):
    port, tok = srv
    _mk_session(port, tok, principal="owner1")
    st, r = _req(port, tok, "GET", "/audit")
    assert st == 200
    acts = [i["action"] for i in r["items"]]
    assert "session.create" in acts
