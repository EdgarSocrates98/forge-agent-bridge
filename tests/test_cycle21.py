"""Cycle 21 — real adapters (unit-level event mapping) + session metadata
endpoints (§20.3) + honest capability gates."""


def test_acp_update_mapping():
    from forge_agent_bridge.providers.acp_adapter import _map_acp_update
    n = {"params": {"update": {"sessionUpdate": "agent_message_chunk",
                              "content": {"type": "text", "text": "hi"}}}}
    assert _map_acp_update(n)["type"] == "content_delta"
    n2 = {"params": {"update": {"sessionUpdate": "tool_call", "title": "Bash"}}}
    assert _map_acp_update(n2)["type"] == "tool_call"
    n3 = {"params": {"update": {"sessionUpdate": "plan", "entries": [{"x": 1}]}}}
    assert _map_acp_update(n3)["type"] == "plan_update"
    n4 = {"params": {"update": {"sessionUpdate": "weird_new_kind"}}}
    assert _map_acp_update(n4)["type"] == "unknown"  # preserved, never dropped


def test_claude_event_mapping():
    from forge_agent_bridge.providers.claude import _map_claude
    ev = _map_claude({"type": "stream_event", "event": {
        "type": "content_block_delta", "delta": {"text": "tok"}}})
    assert ev["type"] == "content_delta" and ev["params"]["text"] == "tok"
    ev = _map_claude({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read"}]}})
    assert ev["type"] == "tool_call" and ev["params"]["name"] == "Read"
    ev = _map_claude({"type": "result",
                      "usage": {"input_tokens": 5, "output_tokens": 9}})
    assert ev["type"] == "usage" and ev["params"]["tokens_out"] == 9
    ev = _map_claude({"type": "control_request", "request_id": "r1"})
    assert ev["type"] == "request_permission"


def test_codex_event_mapping():
    from forge_agent_bridge.providers.codex import _map_codex
    ev = _map_codex({"type": "thread.started", "thread_id": "t-1"})
    assert ev["type"] == "session/new" and ev["params"]["native_id"] == "t-1"
    ev = _map_codex({"type": "item.completed",
                     "item": {"type": "agent_message", "text": "done"}})
    assert ev["type"] == "content"
    ev = _map_codex({"type": "item.started",
                     "item": {"type": "command_execution", "command": "ls"}})
    assert ev["type"] == "tool_call"
    ev = _map_codex({"type": "item.completed",
                     "item": {"type": "todo_list", "items": [{"a": 1}]}})
    assert ev["type"] == "plan_update"
    ev = _map_codex({"type": "turn.completed",
                     "usage": {"input_tokens": 3, "output_tokens": 7}})
    assert ev["type"] == "usage"


def test_adapter_capability_gates():
    from forge_agent_bridge.adapter import (
        UnsupportedCapabilityError,
    )
    from forge_agent_bridge.providers.acp_adapter import AcpAdapter
    from forge_agent_bridge.providers.codex import CodexAdapter
    a = AcpAdapter("devin", ["devin", "acp"])
    for fn in (lambda: a.resume_session("x"),
               lambda: a.respond_to_approval("a", True)):
        try:
            fn()
            raise AssertionError("expected unsupported")
        except UnsupportedCapabilityError:
            pass
    c = CodexAdapter()
    try:
        c.respond_to_approval("a", True)
        raise AssertionError("expected unsupported")
    except UnsupportedCapabilityError:
        pass


def test_metadata_store(tmp_path):
    from forge_agent_bridge.metadata import SessionMetaStore
    m = SessionMetaStore(tmp_path / "s.json")
    m.upsert("ses_1", provider="fake", title="investigate churn")
    m.upsert("ses_1", favorite=True)
    got = m.get("ses_1")
    assert got["favorite"] is True and got["title"] == "investigate churn"
    m.upsert("ses_2", provider="claude-code", archived=True)
    assert "ses_2" not in m.list()
    assert "ses_2" in m.list(include_archived=True)
    m.upsert("ses_1", evil_field="x")  # filtered out
    assert "evil_field" not in m.get("ses_1")
    assert m.delete("ses_1") and not m.delete("ses_1")


def test_session_metadata_endpoints(tmp_path, monkeypatch):
    """§20.3 — list, patch, delete over HTTP."""
    import http.client
    import json
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
                  body='{"provider":"fake","product_id":"p1","title":"t1"}',
                  headers=hdr)
        sid = json.loads(c.getresponse().read())["id"]
        c.request("GET", "/agent-sessions", headers=hdr)
        items = json.loads(c.getresponse().read())["items"]
        assert any(i["id"] == sid and i["meta"]["title"] == "t1"
                   for i in items)
        c.request("PATCH", f"/agent-sessions/{sid}",
                  body='{"favorite":true,"title":"renamed"}', headers=hdr)
        meta = json.loads(c.getresponse().read())["meta"]
        assert meta["favorite"] is True and meta["title"] == "renamed"
        c.request("DELETE", f"/agent-sessions/{sid}", headers=hdr)
        body = json.loads(c.getresponse().read())
        assert body["closed"] is True and body["archived"] is True
        # approval endpoint: fake adapter records the response
        c.request("POST", f"/agent-sessions/{sid}/approve",
                  body='{"approval_id":"a1","approved":true}', headers=hdr)
        assert c.getresponse().status == 200
    finally:
        srv.shutdown()
        sup.terminate_all()
