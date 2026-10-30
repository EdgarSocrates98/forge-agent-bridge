"""Cycle 30.2 — regressions found during live provider homologation.

- Resumed sessions must be shared with the requesting principal (found
  via real Codex probe: prompt on resumed session → FAB-FORBIDDEN).
- Codex adapter must run turns inside a trusted (git) workdir.
"""
from __future__ import annotations

import json

import pytest

from conftest import _req
from forge_agent_bridge.adapter import BridgeError
from forge_agent_bridge.providers.codex import CodexAdapter


def test_resumed_session_shared_with_principal(srv):
    """POST /agent-sessions/{sid}/resume binds the new session to the
    caller — without the collab share its own creator cannot prompt."""
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake"}, principal="alice")
    st, r = _req(port, tok, "POST", f"/agent-sessions/{s['id']}/resume",
                 {"provider": "fake", "session_ref": s["id"]},
                 principal="alice")
    assert st == 201, r
    sid2 = r["id"]
    st, b = _req(port, tok, "POST", f"/agent-sessions/{sid2}/prompt",
                 {"text": "hello"}, principal="alice")
    assert st == 200, b
    assert b["accepted"] is True


def test_provider_resume_handoff_shared(srv):
    """The handoff provider-resume path shares the session as well."""
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake"}, principal="alice")
    st, b = _req(port, tok, "POST",
                 f"/agent-sessions/{s['id']}/handoff",
                 {"mode": "provider-resume"}, principal="alice")
    # fake has no provider_session_ref → honest FAB-UNSUPPORTED, or a
    # shared session — either way it must not produce an orphaned one.
    if st == 201:
        sid2 = b["session"]["id"]
        st2, p = _req(port, tok, "POST",
                      f"/agent-sessions/{sid2}/prompt", {"text": "hi"},
                      principal="alice")
        assert st2 == 200, p
    else:
        assert b["error"]["code"] == "FAB-UNSUPPORTED"


def test_codex_workdir_is_trusted(tmp_path, monkeypatch):
    """Turns spawn inside a git-initialized dir — codex refuses to run
    outside a trusted directory (found: prompts drained 0 events when
    the bridge cwd was ~)."""
    monkeypatch.setenv("FAB_PROVIDER_WORKDIR", str(tmp_path / "pw"))
    a = CodexAdapter()
    cwd = a._cwd()
    import os
    assert cwd is not None and os.path.isdir(os.path.join(cwd, ".git"))
    assert a._cwd() == cwd  # idempotent


def test_codex_workdir_absent_returns_none(monkeypatch):
    monkeypatch.delenv("FAB_PROVIDER_WORKDIR", raising=False)
    a = CodexAdapter(workdir=None)
    assert a._cwd() is None


def test_codex_approvals_honestly_unsupported():
    a = CodexAdapter()
    with pytest.raises(BridgeError):
        a.respond_to_approval("ap_x", True)


# -- server-side product→PF re-verification (§5.4) ---------------------------

class _PFStub:
    """Minimal Product Forge context API stub — authorize/check/revoke."""

    def __init__(self) -> None:
        import http.server
        import threading
        stub = self
        stub.records: dict[str, dict] = {}

        class S(http.server.BaseHTTPRequestHandler):
            def _json(self, code: int, data: dict) -> None:
                b = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self) -> None:
                import json as _j
                n = int(self.headers.get("Content-Length", 0))
                body = _j.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/v1/context/authorize":
                    if body.get("product_id") == "prd_gone":
                        return self._json(404, {"error": {
                            "code": "PF-NOT-FOUND",
                            "message": "product not found"}})
                    cid = f"ctx_{len(stub.records) + 1}"
                    stub.records[cid] = {
                        "id": cid, "state": "active",
                        "product_id": body["product_id"],
                        "workspace_id": body.get("workspace_id") or "wsp_pf",
                        "allowed_tools": ["chat"],
                        "policy_version": "forge/PolicyBundle/1",
                        "context_version": 1, "issued_at": "t",
                        "expires_at_ts": 9e18,
                        "revocation_ref": cid}
                    return self._json(201, {"data": stub.records[cid]})
                if self.path.endswith("/revoke"):
                    cid = self.path.rstrip("/").split("/")[-2]
                    stub.records[cid]["state"] = "revoked"
                    return self._json(200, {"data": stub.records[cid]})
                self._json(404, {"error": {"code": "PF-404"}})

            def do_GET(self) -> None:
                cid = self.path.rstrip("/").split("/")[-1]
                rec = stub.records.get(cid)
                if rec:
                    return self._json(200, {"data": rec})
                self._json(404, {"error": {"code": "PF-NOT-FOUND"}})

            def log_message(self, *a: object) -> None:
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), S)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.srv.shutdown()


@pytest.fixture
def pf_stub_env(monkeypatch):
    stub = _PFStub()
    monkeypatch.setenv("FAB_PF_BASE_URL", f"http://127.0.0.1:{stub.port}")
    monkeypatch.setenv("FAB_PF_TOKEN", "stub-tok")
    monkeypatch.setenv("FAB_PF_CHECK_TTL", "0")  # every prompt re-checks
    yield stub
    stub.stop()


def test_pf_authorize_and_prompt_reverify(pf_stub_env, srv):
    """Session bound to a product gets a PF-issued server_ref; prompt
    re-verification blocks once PF reports the context revoked."""
    port, tok = srv
    st, s = _req(port, tok, "POST", "/agent-sessions",
                 {"provider": "fake", "product_id": "prd_pay",
                  "workspace_id": "wsp_pf"}, principal="alice")
    assert st == 201, s
    ctx = s["context"]
    assert ctx["schema"] == "forge/ProductAgentSessionContext/v2"
    assert ctx["server_ref"].startswith("ctx_")
    assert ctx["session_id"] == s["id"]
    sid = s["id"]
    st, b = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "hi"}, principal="alice")
    assert st == 200, b
    # revoke server-side → next prompt must be denied
    cid = ctx["server_ref"]
    pf_stub_env.records[cid]["state"] = "revoked"
    st, b = _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": "again"}, principal="alice")
    assert st == 403, b
    assert "FORBIDDEN" in b["error"]["code"]


def test_pf_authorize_denial_blocks_create(pf_stub_env, srv):
    """A real PF denial (unknown product) fails session create closed."""
    port, tok = srv
    st, s = _req(port, tok, "POST", "/agent-sessions",
                 {"provider": "fake", "product_id": "prd_gone"})
    assert st in (502, 403, 422, 404), s


def test_pf_unverified_when_unconfigured(monkeypatch, srv):
    """No PF configured → product binding still allowed but honestly
    marked unverified (best-effort default), not silently trusted."""
    monkeypatch.delenv("FAB_PF_BASE_URL", raising=False)
    monkeypatch.delenv("FAB_PF_TOKEN", raising=False)
    monkeypatch.delenv("FAB_PF_VERIFY", raising=False)
    port, tok = srv
    st, s = _req(port, tok, "POST", "/agent-sessions",
                 {"provider": "fake", "product_id": "prd_x"})
    assert st == 201, s
    assert s["context"]["server_ref"] == ""
    st, det = _req(port, tok, "GET", "/agent-sessions")
    item = next(i for i in det["items"] if i["id"] == s["id"])
    assert "unverified" in str(item.get("meta", {}).get("pf_verify", ""))


def test_sse_cors_headers(srv):
    """SSE endpoint must emit ACAO for allowed origins and preflight
    must allow Last-Event-ID — both were missing (found via real
    Chromium fetch in e2e/test_chat_streaming)."""
    import http.client

    from forge_agent_bridge import local_bridge
    local_bridge._ALLOWED_ORIGINS.add("http://127.0.0.1:4200")
    port, tok = srv
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("OPTIONS", "/agent-sessions/x/stream",
              headers={"Origin": "http://127.0.0.1:4200",
                       "Access-Control-Request-Headers": "last-event-id"})
    r = c.getresponse(); r.read(); c.close()
    assert "last-event-id" in \
        r.getheader("Access-Control-Allow-Headers").lower()
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", f"/agent-sessions/{s['id']}/stream?after_seq=0",
              headers={"Authorization": f"Bearer {tok}",
                       "Origin": "http://127.0.0.1:4200"})
    r = c.getresponse()
    r.read(200)  # partial read is enough — headers are what we assert
    c.close()
    assert r.getheader("Access-Control-Allow-Origin") == \
        "http://127.0.0.1:4200"


def test_diagnostics_endpoint_shape(srv):
    port, tok = srv
    st, body = _req(port, tok, "GET", "/diagnostics")
    assert st == 200
    assert body["schema"] == "forge/DiagnosticReport/1"
    assert body["bridge"]["version"]
    assert body["bridge"]["state_dir"]
    ids = [p["id"] for p in body["providers"]]
    assert "fake" in ids and "codex" in ids
    fake = next(p for p in body["providers"] if p["id"] == "fake")
    assert fake["installed"] is True
    assert "chat" in fake["capabilities"]
    assert "sessions" in body and "checks" in body
    names = [c["name"] for c in body["checks"]]
    assert "state-dir" in names and "event-store" in names


def test_mcp_doctor_classifies(srv):
    port, tok = srv
    st, _ = _req(port, tok, "POST", "/mcp", {
        "schema": "forge/MCPServerDescriptor/1",
        "server_id": "test-broken", "name": "Broken",
        "endpoint": "invalid-transport",
        "trust": "revoked", "capabilities": [], "required_scopes": []})
    assert st in (200, 201)
    st, _ = _req(port, tok, "POST",
                 "/mcp/test-broken/health",
                 {"health": "error"})
    assert st == 200
    st, body = _req(port, tok, "GET", "/mcp/doctor")
    assert st == 200
    items = {i["server_id"]: i for i in body["items"]}
    broken = items["test-broken"]
    assert broken["state"] == "error"
    classes = {c["class"] for c in broken["checks"] if "class" in c}
    assert "credential" in classes and "config" in classes
    assert broken["corrective"]
