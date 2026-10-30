"""Cycle 24 — homologation matrix: E2E + negative/security cases.

Every row maps to a release-gate scenario from prompt_evo_ai_workspace §24.
Nothing here may be simulated — failures must surface as typed errors.
"""

from conftest import _req


def _mk_session(port, tok, principal="local", **kw):
    st, s = _req(port, tok, "POST", "/agent-sessions",
                 {"provider": "fake", **kw}, principal)
    assert st == 201, s
    return s["id"]


# -- E2E matrix: full session lifecycle ------------------------------------

def test_e2e_session_lifecycle(srv):
    port, tok = srv
    sid = _mk_session(port, tok, product="p1")
    st, r = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "hello"})
    assert st in (200, 202), r
    st, ev = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                  {"after_seq": 0})
    assert st == 200 and isinstance(ev.get("items"), list)
    st, r = _req(port, tok, "POST", f"/agent-sessions/{sid}/cancel")
    assert st in (200, 202)
    st, _meta = _req(port, tok, "PATCH", f"/agent-sessions/{sid}",
                    {"title": "renamed", "favorite": True})
    assert st == 200
    st, _items = _req(port, tok, "GET", "/agent-sessions")
    assert st == 200


def test_e2e_replay_cursor(srv):
    port, tok = srv
    sid = _mk_session(port, tok)
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt", {"text": "hi"})
    st, e1 = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                  {"after_seq": 0})
    assert st == 200
    events = e1.get("items", [])
    if events:
        last = max(ev.get("seq", 0) for ev in events)
        st, _e2 = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                      {"after_seq": last})
        assert st == 200


# -- Auth ------------------------------------------------------------------

def test_neg_missing_and_wrong_token(srv):
    port, tok = srv
    st, _ = _req(port, None, "GET", "/status")
    assert st == 401
    st, _ = _req(port, "wrong-token", "GET", "/status")
    assert st == 401
    st, _ = _req(port, tok, "GET", "/status")
    assert st == 200


# -- Provider honesty -------------------------------------------------------

def test_neg_unknown_provider(srv):
    port, tok = srv
    st, _e = _req(port, tok, "POST", "/agent-sessions",
                 {"provider": "does-not-exist"})
    assert st in (400, 404, 422, 502)
    st, caps = _req(port, tok, "GET", "/providers")
    assert st == 200
    names = {p.get("name") or p.get("id") for p in
             (caps if isinstance(caps, list)
              else caps.get("providers", caps.get("items", [])))}
    blob = " ".join(str(n).lower() for n in names)
    assert "claude" in blob and "codex" in blob


# -- Malformed input --------------------------------------------------------

def test_neg_malformed_json(srv):
    port, tok = srv
    st, _ = _req(port, tok, "POST", "/agent-sessions", "{not-json", raw=True)
    assert 400 <= st < 500


def test_neg_unknown_route(srv):
    port, tok = srv
    st, _ = _req(port, tok, "GET", "/no-such-route")
    assert st == 404


# -- Authorization / isolation ----------------------------------------------

def test_neg_observer_cannot_act_or_approve(srv):
    port, tok = srv
    sid = _mk_session(port, tok, principal="owner")
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/share",
                 {"visibility": "workspace", "observers": ["watcher"]},
                 "owner")
    assert st == 200
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "x"}, "watcher")
    assert st == 403
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/approve",
                 {"approval_id": "a1", "approved": True}, "watcher")
    assert st == 403


def test_neg_stranger_cannot_hijack(srv):
    port, tok = srv
    sid = _mk_session(port, tok, principal="owner")
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "x"}, "stranger")
    assert st == 403


# -- Budget ------------------------------------------------------------------

def test_neg_budget_enforced(srv):
    port, tok = srv
    st, lim = _req(port, tok, "POST", "/budget/limits",
                   {"scope": "user", "key": "local",
                    "window": "day", "tokens": 0})
    assert st == 201, lim
    sid = _mk_session(port, tok)
    st, _e = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "x"})
    assert st == 429


# -- Path traversal -----------------------------------------------------------

def test_neg_path_traversal(srv):
    port, tok = srv
    for p in ("../x", "/etc/passwd", "..%2f..%2fetc"):
        st, _ = _req(port, tok, "GET", f"/files?path={p}")
        assert st in (400, 403, 404)


# -- Handoff honesty ------------------------------------------------------------

def test_neg_handoff_unsupported_without_session_ref(srv):
    port, tok = srv
    sid = _mk_session(port, tok)
    st, _e = _req(port, tok, "POST", f"/agent-sessions/{sid}/handoff",
                 {"mode": "provider-resume"})
    assert st in (422, 501)
    err = _e.get("error", _e)
    assert "UNSUPPORTED" in str(err) or "resume" in str(err).lower()


def test_handoff_context_rebuild_is_honest(srv):
    port, tok = srv
    sid = _mk_session(port, tok)
    st, h = _req(port, tok, "POST", f"/agent-sessions/{sid}/handoff",
                 {"mode": "context-rebuild"})
    assert st in (200, 201, 202)
    assert h.get("continuity") == "reconstructed"
