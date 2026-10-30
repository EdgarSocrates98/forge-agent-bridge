"""Cycle 27 — product context binding, MCP federation, deltas (§27)."""

from __future__ import annotations

from conftest import _req


def _mk_session(port, tok, context=None):
    body = {"provider": "fake"}
    if context:
        body["context"] = context
    st, s = _req(port, tok, "POST", "/agent-sessions", body)
    assert st == 201
    return s


def test_context_bound_on_create(srv) -> None:
    port, tok = srv
    s = _mk_session(port, tok, context={
        "product_id": "payments",
        "allowed_tools": ["knowledge_query"],
        "allowed_knowledge_sources": ["src-1"],
        "context_version": 7})
    ctx = s["context"]
    assert ctx["schema"] == "forge/ProductAgentSessionContext/v1"
    assert ctx["product_id"] == "payments"
    assert ctx["context_version"] == 7
    assert ctx["identity"]                # bound to authenticated actor
    assert s["meta"]["context_version"] == 7


def test_context_endpoint_and_isolation(srv) -> None:
    port, tok = srv
    a = _mk_session(port, tok, context={"product_id": "p-a"})
    b = _mk_session(port, tok, context={"product_id": "p-b"})
    st, body = _req(port, tok, "GET",
                    f"/agent-sessions/{a['id']}/context")
    assert st == 200
    assert body["context"]["product_id"] == "p-a"
    st, body = _req(port, tok, "GET",
                    f"/agent-sessions/{b['id']}/context")
    assert body["context"]["product_id"] == "p-b"


def test_context_expiry_blocks_prompt(srv) -> None:
    port, tok = srv
    s = _mk_session(port, tok, context={
        "product_id": "p", "expires_at": 1})   # epoch 1970 → expired
    st, body = _req(port, tok, "POST",
                    f"/agent-sessions/{s['id']}/prompt",
                    {"provider": "fake", "text": "hi"})
    assert st in (403, 502)
    assert "expired" in json_err(body)


def json_err(body: dict) -> str:
    return str(body.get("error", {}).get("message", ""))


def test_context_attach_rebinds(srv) -> None:
    port, tok = srv
    s = _mk_session(port, tok, context={"product_id": "p-a"})
    st, _ = _req(port, tok, "POST", "/context/attach", {
        "session_id": s["id"],
        "context": {"product_id": "p-c", "context_version": 9}})
    assert st == 200
    _, body = _req(port, tok, "GET",
                   f"/agent-sessions/{s['id']}/context")
    assert body["context"]["product_id"] == "p-c"
    assert body["context"]["context_version"] == 9


def test_mcp_federation_registry(srv) -> None:
    port, tok = srv
    st, body = _req(port, tok, "GET", "/mcp")
    assert st == 200
    ids = {m["server_id"] for m in body["items"]}
    assert "product-forge" in ids           # seeded federation
    for m in body["items"]:
        assert m["schema"] == "forge/MCPServerDescriptor/v1"
        assert m["health"] == "unverified"  # honest until proven
    st, m = _req(port, tok, "POST", "/mcp", {
        "server_id": "code-atlas", "name": "Code Atlas",
        "capabilities": ["search", "graph"]})
    assert st == 201
    st, m = _req(port, tok, "POST", "/mcp/code-atlas/health",
                 {"health": "verified"})
    assert st == 200 and m["health"] == "verified"


def test_mcp_allowlist_enforced(srv) -> None:
    port, tok = srv
    st, s = _req(port, tok, "POST", "/agent-sessions", {
        "provider": "fake",
        "mcp_servers": ["product-forge", "rogue-server"],
        "context": {"product_id": "p",
                    "mcp_registry": ["product-forge"]}})
    assert st == 201
    assert s.get("mcp_denied") == ["rogue-server"]


def test_context_delta_capture(srv) -> None:
    port, tok = srv
    s = _mk_session(port, tok, context={"product_id": "payments"})
    st, _ = _req(port, tok, "POST", "/context/delta", {
        "session_id": s["id"], "product_id": "payments",
        "statement": "checkout timeout is 30s",
        "evidence_refs": ["ev_1"], "review": "reviewed"})
    assert st == 201
    st, body = _req(port, tok, "GET",
                    "/context/deltas?product_id=payments&review=reviewed")
    assert st == 200
    assert len(body["items"]) == 1
    assert body["items"][0]["schema"] == "forge/AgentContextDelta/v1"
    assert body["items"][0]["reviewer"]    # bound to actor
