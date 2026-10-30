"""Shared fixtures — live local-bridge server with real pairing token."""

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


def _req(port, tok, method, path, body=None, principal=None, raw=False):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json"}
    if tok is not None:
        h["Authorization"] = f"Bearer {tok}"
    if principal:
        h["X-FAB-Principal"] = principal
    payload = body if raw else (json.dumps(body) if body is not None else None)
    c.request(method, path, payload, h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data or b"{}")
    except json.JSONDecodeError:
        return r.status, {"_raw": data.decode("utf-8", "replace")}
