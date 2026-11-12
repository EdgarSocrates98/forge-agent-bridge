"""MCP protocol conformance — legacy + modern eras (deterministic, no IO)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge_agent_bridge.mcp import (
    LATEST_LEGACY,
    SUPPORTED_LEGACY,
    SUPPORTED_MODERN,
)
from forge_agent_bridge.mcp import protocol as P
from forge_agent_bridge.mcp.audit import McpAudit
from forge_agent_bridge.mcp.dispatcher import Dispatcher, ServerContext
from forge_agent_bridge.mcp.security import policy_for
from forge_agent_bridge.mcp.workspace import WorkspaceGuard


@pytest.fixture()
def ctx(tmp_path: Path) -> ServerContext:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    return ServerContext(
        policy=policy_for("corporate-readonly"),
        guard=WorkspaceGuard(tmp_path),
        state_dir=tmp_path / ".state",
        audit=McpAudit(None, enabled=False))


@pytest.fixture()
def disp(ctx):
    return Dispatcher(ctx)


def req(mid, method, params=None):
    m = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        m["params"] = params
    return m


# -- framing ------------------------------------------------------------------

def test_parse_valid_request():
    msg, err = P.parse_line(
        b'{"jsonrpc":"2.0","id":1,"method":"ping"}', max_bytes=1024)
    assert err is None and msg["method"] == "ping"


def test_parse_rejects_oversize():
    _, err = P.parse_line(b" " * 200, max_bytes=100)
    assert err["error"]["code"] == P.PARSE_ERROR


def test_parse_rejects_bad_json():
    _, err = P.parse_line(b"{not json", max_bytes=1024)
    assert err["error"]["code"] == P.PARSE_ERROR


def test_parse_rejects_non_2_0():
    _, err = P.parse_line(b'{"jsonrpc":"1.0","id":1,"method":"x"}',
                          max_bytes=1024)
    assert err["error"]["code"] == P.INVALID_REQUEST


def test_notification_never_answered(disp):
    assert disp.handle({"jsonrpc": "2.0",
                        "method": "notifications/initialized"}) is None


def test_response_message_ignored(disp):
    assert disp.handle({"jsonrpc": "2.0", "id": 9,
                        "result": {}}) is None


# -- legacy era ---------------------------------------------------------------

def test_legacy_handshake_full(disp, ctx):
    r = disp.handle(req(1, "initialize", {
        "protocolVersion": "2025-11-25",
        "clientInfo": {"name": "c", "version": "1"}}))
    res = r["result"]
    assert res["protocolVersion"] == "2025-11-25"
    assert res["serverInfo"]["name"] == "forge-agent-bridge"
    assert ctx.era == "legacy" and ctx.legacy_initialized

    assert disp.handle(req(2, "ping"))["result"] == {}
    tools = disp.handle(req(3, "tools/list"))["result"]["tools"]
    assert len(tools) == 7
    assert all("inputSchema" in t and "name" in t for t in tools)

    call = disp.handle(req(4, "tools/call",
                           {"name": "forge_health", "arguments": {}}))
    assert call["result"]["structuredContent"]["profile"] == "corporate-readonly"
    assert call["result"]["isError"] is False


def test_legacy_older_version_accepted(disp):
    r = disp.handle(req(1, "initialize",
                        {"protocolVersion": "2025-06-18"}))
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_legacy_unknown_version_falls_back(disp):
    r = disp.handle(req(1, "initialize",
                        {"protocolVersion": "1999-01-01"}))
    assert r["result"]["protocolVersion"] == LATEST_LEGACY


def test_modern_version_on_legacy_handshake_refused(disp):
    r = disp.handle(req(1, "initialize",
                        {"protocolVersion": SUPPORTED_MODERN[0]}))
    assert r["error"]["code"] == P.UNSUPPORTED_VERSION
    assert r["error"]["data"]["requested"] == SUPPORTED_MODERN[0]


def test_tools_before_handshake_refused(disp):
    r = disp.handle(req(1, "tools/list"))
    assert r["error"]["code"] == P.UNSUPPORTED_VERSION


def test_request_ids_preserved(disp):
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    for mid in ("str-id", 42):
        r = disp.handle(req(mid, "ping"))
        assert r["id"] == mid


def test_legacy_unknown_method(disp):
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    r = disp.handle(req(2, "resources/list"))
    assert r["error"]["code"] == P.METHOD_NOT_FOUND


# -- modern era ---------------------------------------------------------------

def test_modern_discover(disp, ctx):
    r = disp.handle(req(1, "server/discover"))
    res = r["result"]
    assert res["resultType"] == "complete"
    assert set(SUPPORTED_MODERN) & set(res["supportedVersions"])
    assert "_meta" in res and "io.modelcontextprotocol/serverInfo" in res["_meta"]
    assert ctx.era == "modern"


def test_modern_per_request_meta_version(disp):
    v = SUPPORTED_MODERN[0]
    r = disp.handle(req(1, "tools/list", {
        "_meta": {"io.modelcontextprotocol/protocolVersion": v}}))
    assert "tools" in r["result"]
    assert disp.ctx.negotiated_version == v


def test_modern_unsupported_version_error(disp):
    r = disp.handle(req(1, "tools/list", {
        "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-01-01"}}))
    assert r["error"]["code"] == P.UNSUPPORTED_VERSION
    d = r["error"]["data"]
    assert d["requested"] == "2026-01-01"
    assert d["supported"] == list(
        SUPPORTED_MODERN + SUPPORTED_LEGACY)


def test_modern_ping_removed(disp):
    v = SUPPORTED_MODERN[0]
    r = disp.handle(req(1, "ping", {
        "_meta": {"io.modelcontextprotocol/protocolVersion": v}}))
    assert r["error"]["code"] == P.METHOD_NOT_FOUND


def test_modern_tools_call(disp):
    v = SUPPORTED_MODERN[0]
    r = disp.handle(req(1, "tools/call", {
        "name": "forge_health", "arguments": {},
        "_meta": {"io.modelcontextprotocol/protocolVersion": v}}))
    assert r["result"]["structuredContent"]["protocol"]["era"] == "modern"


# -- tools/call semantics ------------------------------------------------------

def test_call_unknown_tool(disp):
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    r = disp.handle(req(2, "tools/call", {"name": "evil_tool"}))
    assert r["error"]["code"] == P.INVALID_PARAMS


def test_call_invalid_args(disp):
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    # policy denies run before arg validation — use an allowed tool
    r = disp.handle(req(2, "tools/call", {
        "name": "forge_workspace_summary",
        "arguments": {"max_depth": "deep"}}))
    assert r["error"]["code"] == P.INVALID_PARAMS


def test_call_denied_before_arg_validation(disp):
    """Policy denial wins over schema errors — don't validate what you
    may not execute (fail-closed ordering)."""
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    r = disp.handle(req(2, "tools/call", {
        "name": "forge_gh_pr_read",
        "arguments": {"repo": "a/b", "pr": "not-an-int"}}))
    assert r["error"]["code"] == P.TOOL_DENIED


def test_call_extra_args_rejected(disp):
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    r = disp.handle(req(2, "tools/call", {
        "name": "forge_health", "arguments": {"evil": True}}))
    assert r["error"]["code"] == P.INVALID_PARAMS


def test_result_shape_has_structured_content(disp):
    disp.handle(req(1, "initialize", {"protocolVersion": "2025-11-25"}))
    r = disp.handle(req(2, "tools/call",
                        {"name": "forge_health", "arguments": {}}))
    res = r["result"]
    assert res["content"][0]["type"] == "text"
    json.loads(res["content"][0]["text"])  # content text is valid JSON
    assert res["structuredContent"]["server"] == "forge-agent-bridge"
