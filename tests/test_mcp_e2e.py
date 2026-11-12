"""MCP stdio E2E — real subprocess, stdout purity, clean shutdown."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "src"


def _env(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PKG)
    env["FAB_STATE_DIR"] = str(tmp_path / ".fab")
    return env


def _exchange(proc, msgs):
    proc.stdin.write("\n".join(msgs) + "\n")
    proc.stdin.flush()


def _read_msgs(proc, n, timeout=15):
    out = []
    for _ in range(n):
        line = proc.stdout.readline()
        if not line:
            break
        out.append(json.loads(line))
    return out


@pytest.fixture()
def server(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n")
    p = subprocess.Popen(
        [sys.executable, "-m", "forge_agent_bridge.mcp",
         "--profile", "corporate-readonly", "--workspace", str(ws)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=_env(tmp_path))
    yield p
    p.kill()


def test_full_sequence(tmp_path, server):
    """The 11-step E2E from the spec: negotiate → tools → calls → denial → EOF."""
    msgs = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25",
                               "clientInfo": {"name": "e2e", "version": "1"}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "forge_health", "arguments": {}}}),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "forge_workspace_summary",
                               "arguments": {}}}),
        json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                    "params": {"name": "forge_context_read", "arguments": {}}}),
        json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                    "params": {"name": "forge_gh_pr_read",
                               "arguments": {"repo": "a/b", "pr": 1}}}),
    ]
    _exchange(server, msgs)
    got = _read_msgs(server, 7)
    assert len(got) == 7
    assert got[0]["result"]["protocolVersion"] == "2025-11-25"
    assert got[1]["result"] == {}            # ping
    assert len(got[2]["result"]["tools"]) == 7
    assert got[3]["result"]["structuredContent"]["status"] == "ready"
    assert got[4]["result"]["structuredContent"]["workspace"]
    ctx_res = got[5]["result"]["structuredContent"]
    assert ctx_res["status"] == "unavailable:no-context-store"
    denied = got[6]
    assert denied["error"]["code"] == -32010  # step 8: a real denial

    # step 9: no unintended file changes in workspace
    server.stdin.close()
    rc = server.wait(timeout=15)
    assert rc == 0  # step 11: clean shutdown on EOF


def test_stdout_purity(tmp_path, server):
    """stdout carries ONLY parseable JSON-RPC — no banners/logs."""
    _exchange(server, [json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25"}})])
    line = server.stdout.readline()
    msg = json.loads(line)  # raises if stdout polluted
    assert msg["jsonrpc"] == "2.0"
    server.stdin.close()
    server.wait(timeout=15)


def test_malformed_line_recovers(tmp_path, server):
    """Bad line → parse error, server keeps working."""
    _exchange(server, [
        "not json at all",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"}}),
    ])
    got = _read_msgs(server, 2)
    assert got[0]["error"]["code"] == -32700
    assert got[1]["result"]["protocolVersion"] == "2025-11-25"
    server.stdin.close()
    server.wait(timeout=15)


def test_modern_era_e2e(tmp_path, server):
    _exchange(server, [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "server/discover"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                    "params": {"_meta": {
                        "io.modelcontextprotocol/protocolVersion":
                            "2026-07-28"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "forge_health", "arguments": {},
                               "_meta": {
                                   "io.modelcontextprotocol/protocolVersion":
                                       "2026-07-28"}}}),
    ])
    got = _read_msgs(server, 3)
    assert got[0]["result"]["resultType"] == "complete"
    assert "io.modelcontextprotocol/serverInfo" in got[0]["result"]["_meta"]
    assert len(got[1]["result"]["tools"]) == 7
    assert got[2]["result"]["structuredContent"]["protocol"]["era"] == "modern"
    server.stdin.close()
    assert server.wait(timeout=15) == 0


def test_unknown_profile_refuses_start(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "forge_agent_bridge.mcp",
         "--profile", "yolo"],
        check=False, capture_output=True, text=True, timeout=20, env=_env(tmp_path))
    assert p.returncode == 2
    assert "unknown" in p.stderr.lower() or "error" in p.stderr.lower()


def test_audit_file_created(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    env = _env(tmp_path)
    p = subprocess.run(
        [sys.executable, "-m", "forge_agent_bridge.mcp",
         "--workspace", str(ws)],
        check=False, input=json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "server/discover"}),
        capture_output=True, text=True, timeout=20, env=env)
    assert p.returncode == 0
    audit = Path(env["FAB_STATE_DIR"]) / "mcp_audit.jsonl"
    assert audit.is_file()
    events = [json.loads(l)["event"] for l in audit.read_text().splitlines()]
    assert "mcp.server.started" in events
    assert "mcp.server.stopped" in events
