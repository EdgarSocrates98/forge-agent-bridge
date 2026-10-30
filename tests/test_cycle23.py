"""Cycle 23 — runners, budgets, collaboration enforcement, handoff."""

import http.client
import json
import threading

import pytest


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    from forge_agent_bridge import local_bridge
    monkeypatch.setattr(local_bridge, "STATE_DIR", tmp_path / "fb")
    monkeypatch.chdir(tmp_path)
    tok = local_bridge.pair_token()
    handler, sup = local_bridge.make_app()
    from http.server import ThreadingHTTPServer
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], tok
    s.shutdown()
    sup.terminate_all()


def _req(port, tok, method, path, body=None, principal=None):
    c = http.client.HTTPConnection("127.0.0.1", port)
    h = {"Authorization": f"Bearer {tok}",
         "Content-Type": "application/json"}
    if principal:
        h["X-FAB-Principal"] = principal
    c.request(method, path, body=json.dumps(body or {}), headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read())


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
                 {"id": "r1", "kind": "remote", "endpoint": "http://x:9"})
    assert st == 201 and r["state"] == "unverified"  # honest — never probed
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
