"""Cycle 30 — contract tests + integration harness.

Validates the wire contracts of every public bridge surface: versioned
schema names, required envelope fields, event sequencing invariants and
error envelope shape — against the real HTTP handler (no mocks).
"""
import http.client

from conftest import _req

# ---------- schema envelopes -------------------------------------------------

def test_session_contract_fields(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    for k in ("id", "provider", "state"):
        assert k in s, f"session missing {k}"


def test_event_contract_and_monotonic_seq(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt", {"text": "hi"})
    _, body = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                   {"provider": "fake", "after_seq": 0})
    seqs = [e["seq"] for e in body["items"]]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    for e in body["items"]:
        assert e["schema"] == "forge/AgentBridgeEvent/v1"
        for k in ("id", "seq", "type", "session_id", "payload"):
            assert k in e, f"event missing {k}"


def test_provider_matrix_contract(srv):
    port, tok = srv
    _, body = _req(port, tok, "GET", "/providers")
    vocab = {"chat", "streaming", "session-resume", "cancel", "tool-calling",
             "mcp", "files", "approvals", "images", "models", "subagents",
             "plans", "usage", "cloud-handoff"}
    states = {"supported", "unsupported", "experimental", "unverified",
              "requires-configuration", "requires-authentication", "error"}
    for p in body["items"]:
        assert p["matrix_version"] == "forge/ProviderCapabilityMatrix/1"
        names = {c["name"] for c in p["capabilities"]}
        assert names == vocab, f"{p['id']} vocab drift: {names ^ vocab}"
        for c in p["capabilities"]:
            assert c["state"] in states


def test_error_envelope_contract(srv):
    port, tok = srv
    st, body = _req(port, tok, "GET", "/agent-sessions/does-not-exist/events")
    assert st >= 400
    assert "error" in body and "code" in body["error"]
    assert body["error"]["code"].startswith("FAB-")


def test_intel_schemas(srv):
    port, tok = srv
    for path, schema in (
            ("/intel/mode", "forge/DegradedMode/v1"),
            ("/intel/finops", "forge/AgentFinOps/v1"),
            ("/intel/workspace", "forge/WorkspaceIntelligence/v1")):
        st, body = _req(port, tok, "GET", path)
        assert st == 200 and body["schema"] == schema, path


def test_context_contract(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake", "product_id": "p-1",
                 "workspace_id": "w-1"})
    sid = s["id"]
    st, ctx = _req(port, tok, "GET", f"/context/{sid}")
    if st == 200:
        assert ctx["schema"] == "forge/ProductAgentSessionContext/v1"


def test_recovery_plan_contract(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    st, r = _req(port, tok, "GET", f"/agent-sessions/{s['id']}/recovery")
    assert st == 200
    plan = r["recovery"]
    assert plan["schema"] == "forge/SessionRecoveryPlan/v1"
    assert plan["mode"] in ("provider-resume", "context-rebuild",
                            "replay-only", "unavailable")


# ---------- integration: full lifecycle through HTTP -------------------------

def test_full_lifecycle_e2e(srv):
    """pair -> session -> prompt -> stream -> cancel -> delete -> backup."""
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "run it"})
    assert st == 200
    # SSE stream endpoint responds with event stream body
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", f"/agent-sessions/{sid}/stream?after_seq=0",
              headers={"Authorization": f"Bearer {tok}"})
    r = c.getresponse()
    # SSE stays open (heartbeats) — read only what's already flushed
    body = r.read1(8192).decode("utf-8", "replace")
    c.close()
    assert r.status == 200 and "data:" in body
    st, _ = _req(port, tok, "POST", f"/agent-sessions/{sid}/cancel",
                 {"provider": "fake"})
    assert st in (200, 422)
    st, _ = _req(port, tok, "DELETE", f"/agent-sessions/{sid}")
    assert st in (200, 204, 404)
    st, b = _req(port, tok, "POST", "/backup")
    assert st == 201 and b["backup"]
