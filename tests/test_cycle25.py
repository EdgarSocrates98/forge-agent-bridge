"""Cycle 25 — security hardening abuse tests (§25.2–25.8)."""

import base64
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
    yield s.server_address[1], tok, sup
    s.shutdown()
    sup.terminate_all()


def _req(port, tok, method, path, body=None, hdr=None):
    c = http.client.HTTPConnection("127.0.0.1", port)
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if hdr:
        h.update(hdr)
    c.request(method, path, body=json.dumps(body or {}), headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}"), dict(r.getheaders())


def test_no_arbitrary_exec(srv):
    """§25.2 — client cannot supply argv; only typed provider spawn."""
    port, tok, _ = srv
    st, _r, _ = _req(port, tok, "POST", "/sessions",
                    {"cmd": ["sh", "-c", "id"]})
    assert st == 422
    st, _r, _ = _req(port, tok, "POST", "/sessions",
                    {"op": "spawn-provider", "provider": "bogus"})
    assert st == 422


def test_approval_token_bound_and_single_use(srv):
    """§25.4 — approvals bind op+args digest; replay + tamper refused."""
    port, tok, _ = srv
    (srv[2] and None)
    b64 = base64.b64encode(b"x").decode()
    st, r, _ = _req(port, tok, "POST", "/files/upload",
                    {"path": "a.txt", "content_b64": b64})
    assert st == 409 and r["approval_request"]["args_digest"]
    ap = r["approval_request"]
    st, g, _ = _req(port, tok, "POST",
                    f"/approvals/{ap['approval_id']}/resolve",
                    {"approved": True})
    assert g["granted"] and g["approval_token"]
    # argument tamper — different content under same token → refused
    st, _e, _ = _req(port, tok, "POST", "/files/upload",
                     {"path": "a.txt",
                      "content_b64": base64.b64encode(b"y").decode(),
                      "approval_token": g["approval_token"]})
    assert st == 403
    # correct args → consumed once
    st, _r, _ = _req(port, tok, "POST", "/files/upload",
                     {"path": "a.txt", "content_b64": b64,
                      "approval_token": g["approval_token"]})
    assert st == 200
    st, _e, _ = _req(port, tok, "POST", "/files/upload",
                     {"path": "a.txt", "content_b64": b64,
                      "approval_token": g["approval_token"]})
    assert st == 403  # replay refused


def test_session_token_pairing_and_revocation(srv):
    """§25.6 — master token exchanges for scoped session; revoke kills it."""
    port, tok, _ = srv
    st, r, _ = _req(port, tok, "POST", "/pair/exchange",
                    {"pair_token": tok, "device_name": "portal-1"})
    assert st == 201 and r["session_token"]
    stok = r["session_token"]
    st, _, _ = _req(port, stok, "GET", "/status")
    assert st == 200
    dev = r["device"]["device_id"]
    st, _, _ = _req(port, tok, "DELETE", f"/pair/devices/{dev}")
    assert _[2] if False else st == 200
    st, _, _ = _req(port, stok, "GET", "/status")
    assert st == 401  # revoked device no longer authenticates


def test_session_token_cannot_impersonate(srv):
    """§25.6/25.3 — session token actor is the device, not the header."""
    port, tok, _ = srv
    st, r, _ = _req(port, tok, "POST", "/pair/exchange",
                    {"pair_token": tok, "device_name": "dev-ana"})
    stok = r["session_token"]
    st, s, _ = _req(port, stok, "POST", "/agent-sessions",
                    {"provider": "fake"})
    assert st == 201
    sid = s["id"]
    # even with an impersonating header, the session token acts as device
    st, _, _ = _req(port, stok, "POST", f"/agent-sessions/{sid}/prompt",
                    {"text": "hi"}, {"X-FAB-Principal": "admin"})
    assert st == 200  # device owns the session — header can't hijack


def test_http_hardening(srv):
    """§25.5 — host check, body cap, origin, preflight."""
    port, tok, _ = srv
    # DNS-rebinding: foreign Host rejected
    st, _, _ = _req(port, tok, "GET", "/status",
                    hdr={"Host": "evil.example.com"})
    assert st == 403
    # body cap (cap lowered for the test — a real 8MiB body would race the
    # server's early 413 close and break the client pipe)
    from forge_agent_bridge import local_bridge as lb
    lb.MAX_BODY = 128
    st, r, _ = _req(port, tok, "POST", "/files/upload",
                    {"path": "big", "pad": "x" * 4096})
    assert st == 413
    lb.MAX_BODY = 8 * 1024 * 1024
    # browser origin allowed (loopback), echoed back
    st, _, h = _req(port, tok, "GET", "/status",
                    hdr={"Origin": "http://localhost:4200"})
    assert st == 200 and h.get("Access-Control-Allow-Origin") == \
        "http://localhost:4200"
    # hostile origin → no CORS grant
    st, _, h = _req(port, tok, "GET", "/status",
                    hdr={"Origin": "https://evil.example.com"})
    assert st == 403
    # OPTIONS preflight
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("OPTIONS", "/agent-sessions",
              headers={"Origin": "http://localhost:4200",
                       "Access-Control-Request-Method": "POST"})
    r = c.getresponse()
    r.read()
    assert r.status == 204


def test_runner_ssrf(srv):
    """§25.7 — blocked ranges and unproven identity rejected."""
    port, tok, _ = srv
    for ep in ("http://169.254.169.254/latest/meta-data",
               "ftp://x", "http://[::1]/"):
        st, _r, _ = _req(port, tok, "POST", "/runners",
                         {"id": "b1", "kind": "remote", "endpoint": ep})
        assert st == 422, ep


def test_pair_rotation(srv):
    port, tok, _ = srv
    st, r, _ = _req(port, tok, "POST", "/pair/rotate",
                    {"pair_token": tok})
    assert st == 200 and r["pair_token"] != tok
    st, _, _ = _req(port, tok, "GET", "/status")
    assert st == 401  # old master dead
    st, _, _ = _req(port, r["pair_token"], "GET", "/status")
    assert st == 200
