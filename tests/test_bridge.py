"""Cycle 19 — bridge foundation contract tests (fake provider per spec)."""

import json


def _fake():
    from forge_agent_bridge.providers.fake import FakeAdapter
    return FakeAdapter()


def test_provider_detection_honest():
    from forge_agent_bridge.registry import REGISTRY
    ds = REGISTRY.detect_all()
    assert len(ds) == 4  # claude, codex, devin, fake
    fake = next(d for d in ds if d.id == "fake")
    assert fake.capabilities and all(c.state.value for c in fake.capabilities)
    real = next(d for d in ds if d.id == "claude-code")
    assert real.auth_state.value in ("unverified", "unauthenticated")


def test_session_lifecycle_and_events():
    from forge_agent_bridge.events import EventBuffer, normalize
    a = _fake()
    a.initialize()
    s = a.create_session(product_id="p1")
    assert s.state.value == "active" and s.resumable
    a.send_prompt(s.id, "hello")
    buf = EventBuffer(s.id)
    types = []
    for native in a.stream_events(s.id):
        ev = normalize(native, "fake", s.id)
        assert ev["schema"] == "forge/AgentBridgeEvent/v1"
        assert ev["seq"] > 0 and ev["session_id"] == s.id
        assert buf.push(ev)
        types.append(ev["type"])
    assert types[0] == "session.created"
    assert "message.delta" in types and "tool.completed" in types
    assert "usage.updated" in types
    # dedupe: re-pushing same event id is rejected
    assert not buf.push(buf.replay()[0])
    # replay window
    assert buf.replay(after_seq=2)


def test_resume_cancel_close_and_errors():
    from forge_agent_bridge.adapter import SessionError
    a = _fake()
    s = a.create_session()
    r = a.resume_session(s.id)
    assert r.state.value == "active"
    a.cancel(s.id)
    assert s.id in a.cancelled
    a.close_session(s.id)
    assert a.sessions[s.id].state.value == "closed"
    try:
        a.resume_session("nope")
        raise AssertionError("expected SessionError")
    except SessionError:
        pass


def test_unmapped_native_event_preserved():
    from forge_agent_bridge.events import normalize
    ev = normalize({"type": "vendor.weird", "x": 1}, "p", "s1")
    assert ev["type"] == "runtime.error"
    assert ev["payload"]["native_type"] == "vendor.weird"
    assert ev["raw"]["x"] == 1  # native preserved for diagnostics


def test_capability_matrix_states():
    from forge_agent_bridge.registry import REGISTRY
    states = {c.state.value for d in REGISTRY.detect_all() for c in d.capabilities}
    assert "unverified" in states and "requires-configuration" in states


def test_acp_client_fake_server():
    """§19 testes — fake protocol server: initialize + session + prompt."""
    import subprocess
    import sys
    import threading

    srv = subprocess.Popen([sys.executable, "-c", '''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    if "id" not in req:
        continue
    m, rid = req["method"], req["id"]
    if m == "initialize":
        out = {"jsonrpc":"2.0","id":rid,"result":{"protocolVersion":1}}
    elif m == "session/new":
        out = {"jsonrpc":"2.0","id":rid,"result":{"sessionId":"s-1"}}
    elif m == "session/prompt":
        out = {"jsonrpc":"2.0","id":rid,"result":{"stopReason":"end_turn"}}
    else:
        out = {"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"unknown"}}
    sys.stdout.write(json.dumps(out) + "\\n"); sys.stdout.flush()
'''], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    # drive client over the same process pair via a socket-like shim:
    from forge_agent_bridge.acp import AcpClient
    # wrap: client expects to spawn; instead reuse the spawned process pipes
    c = AcpClient([sys.executable, "-c", "pass"])
    c.proc = srv
    t = threading.Thread(target=c._read_loop, daemon=True)
    t.start()
    res = c.initialize()
    assert res["protocolVersion"] == 1
    sid = c.new_session()
    assert sid == "s-1"
    pr = c.prompt(sid, "hi")
    assert pr["stopReason"] == "end_turn"
    srv.terminate()


def test_local_bridge_auth_and_supervisor(tmp_path, monkeypatch):
    """§6.4/19.5 — localhost service: auth gate + process cleanup."""
    import http.client
    import threading

    from forge_agent_bridge import local_bridge

    monkeypatch.setattr(local_bridge, "STATE_DIR", tmp_path / "fb")
    tok = local_bridge.pair_token()
    assert tok and (tmp_path / "fb" / "pair.token").exists()
    handler, sup = local_bridge.make_app()
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # unauth → 401
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", "/status")
        assert c.getresponse().status == 401
        # auth → 200
        c.request("GET", "/status", headers={"Authorization": f"Bearer {tok}"})
        assert c.getresponse().status == 200
        # spawn supervised process, then terminate
        c.request("POST", "/sessions",
                  body='{"cmd": ["sleep", "30"]}',
                  headers={"Authorization": f"Bearer {tok}",
                           "Content-Type": "application/json"})
        resp = json.loads(c.getresponse().read())
        sid = resp["session_id"]
        assert sid in sup.running()
        c.request("DELETE", f"/sessions/{sid}",
                  headers={"Authorization": f"Bearer {tok}"})
        assert c.getresponse().status == 200
        import time
        for _ in range(50):
            if sid not in sup.running():
                break
            time.sleep(0.05)
        assert sid not in sup.running()
    finally:
        srv.shutdown()
        sup.terminate_all()


def test_orchestrator_full_flow():
    """§20 backend — session → prompt → drain → replay → close via orchestrator."""
    from forge_agent_bridge.orchestrator import build_orchestrator
    o = build_orchestrator("fake")
    s = o.create_session(product_id="p1")
    o.prompt(s.id, "what is E42?")
    n = o.drain(s.id)
    assert n >= 5
    evs = o.replay(s.id)
    types = [e["type"] for e in evs]
    assert types[0] == "session.created" and "usage.updated" in types
    assert o.replay(s.id, after_seq=3)[0]["seq"] > 3
    o.close(s.id)
    assert o.sessions[s.id]
    from forge_agent_bridge.adapter import BridgeError
    try:
        o.prompt("nope", "x")
        raise AssertionError("expected error")
    except BridgeError as e:
        assert e.code == "FAB-SESSION"


def test_local_bridge_agent_session_http(tmp_path, monkeypatch):
    """Cycle 20 wire — create session → prompt → events over HTTP."""
    import http.client
    import threading

    from forge_agent_bridge import local_bridge

    monkeypatch.setattr(local_bridge, "STATE_DIR", tmp_path / "fb")
    tok = local_bridge.pair_token()
    handler, sup = local_bridge.make_app()
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    try:
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("POST", "/agent-sessions",
                  body='{"provider":"fake","product_id":"p1"}', headers=hdr)
        r = c.getresponse()
        sid = json.loads(r.read())["id"]
        assert r.status == 201
        c.request("POST", f"/agent-sessions/{sid}/prompt",
                  body='{"text":"hi","provider":"fake"}', headers=hdr)
        assert c.getresponse().status == 200
        c.request("POST", f"/agent-sessions/{sid}/events",
                  body='{"provider":"fake","after_seq":0}', headers=hdr)
        evs = json.loads(c.getresponse().read())["items"]
        assert any(e["type"] == "message.completed" for e in evs)
        assert all(e["schema"] == "forge/AgentBridgeEvent/v1" for e in evs)
    finally:
        srv.shutdown()
        sup.terminate_all()
