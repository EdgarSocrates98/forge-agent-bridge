"""Cycle 22 — file service security gates + artifact derivation."""


def test_file_service_security_and_ops(tmp_path, monkeypatch):
    from forge_agent_bridge import local_bridge
    monkeypatch.setattr(local_bridge, "STATE_DIR", tmp_path / "fb")
    from forge_agent_bridge.adapter import BridgeError
    from forge_agent_bridge.files import FileService

    root = tmp_path / "ws"
    root.mkdir()
    (root / "doc.md").write_text("# Hello\ncontent")
    (root / "bin.pdf").write_bytes(b"%PDF-1.4 fake")
    fs = FileService(root)

    # list + preview
    names = {e["name"] for e in fs.list_dir(".")}
    assert "doc.md" in names
    pv = fs.preview("doc.md")
    assert pv["kind"] == "text" and "Hello" in pv["preview"]
    pv2 = fs.preview("bin.pdf")
    assert pv2["kind"] == "binary" and pv2["preview"] is None

    # traversal is forbidden
    try:
        fs.preview("../secret.txt")
        raise AssertionError("expected forbidden")
    except BridgeError as e:
        assert e.code == "FAB-FORBIDDEN"

    # write requires approval; snapshot on overwrite; restore works
    try:
        fs.upload("doc.md", b"v2", approved=False)
        raise AssertionError("expected approval gate")
    except BridgeError as e:
        assert e.code == "FAB-APPROVAL-REQUIRED"
    fs.upload("doc.md", b"v2", approved=True)
    hist = fs.history("doc.md")
    assert hist and hist[0]["version"]
    fs.upload("doc.md", b"v3", approved=True)
    fs.restore("doc.md", hist[0]["version"], approved=True)
    assert (root / "doc.md").read_text() == "v2"


def test_file_endpoints_http(tmp_path, monkeypatch):
    import base64
    import http.client
    import json
    import threading

    from forge_agent_bridge import local_bridge
    monkeypatch.setattr(local_bridge, "STATE_DIR", tmp_path / "fb")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("alpha")
    tok = local_bridge.pair_token()
    handler, sup = local_bridge.make_app()
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    try:
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("POST", "/files/list", body='{"path":"."}', headers=hdr)
        items = json.loads(c.getresponse().read())["items"]
        assert any(i["name"] == "a.txt" for i in items)
        c.request("POST", "/files/preview", body='{"path":"a.txt"}', headers=hdr)
        assert json.loads(c.getresponse().read())["preview"] == "alpha"
        c.request("POST", "/files/upload",
                  body=json.dumps({"path": "b.txt",
                                   "content_b64": base64.b64encode(b"beta").decode(),
                                   "approved": True}), headers=hdr)
        assert json.loads(c.getresponse().read())["saved"] is True
        c.request("POST", "/files/download", body='{"path":"b.txt"}', headers=hdr)
        b64 = json.loads(c.getresponse().read())["content_b64"]
        assert base64.b64decode(b64) == b"beta"
        c.request("POST", "/files/preview", body='{"path":"../x"}', headers=hdr)
        assert c.getresponse().status == 403
    finally:
        srv.shutdown()
        sup.terminate_all()


def test_artifacts_derivation():
    from forge_agent_bridge.orchestrator import build_orchestrator
    o = build_orchestrator("fake")
    s = o.create_session()
    o.prompt(s.id, "x")
    o.drain(s.id)
    # fake emits no artifacts — honest empty
    assert o.artifacts(s.id) == []
    # inject an artifact event through the buffer pipeline
    o._push(s.id, {"type": "artifact.created" if False else "tool_result",
                   "params": {"name": "write", "ok": True, "path": "out.md"}})
    arts = o.artifacts(s.id)
    assert arts and arts[0]["path"] == "out.md"
