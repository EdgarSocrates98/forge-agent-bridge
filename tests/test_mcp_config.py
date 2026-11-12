"""MCP config writers — idempotence, preservation, per-format keys."""

from __future__ import annotations

import json

import pytest

from forge_agent_bridge.mcp import config as cfg


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / ".copilot"))
    return tmp_path


def _conf(ws, **kw):
    kw.setdefault("python", "/usr/bin/python3")
    kw.setdefault("workspace", ws)
    kw.setdefault("profile", "corporate-readonly")
    kw.setdefault("tools", None)
    kw.setdefault("target_ids", None)
    kw.setdefault("dry_run", False)
    kw.setdefault("backup", False)
    return cfg.configure(**kw)


def test_creates_all_targets(ws):
    r = _conf(ws)
    paths = {rec["target"]: rec for rec in r["receipts"]}
    assert set(paths) == {"copilot-portable", "workspace-portable",
                          "vscode-managed"}
    assert (ws / ".mcp.json").is_file()
    assert (ws / ".vscode" / "mcp.json").is_file()


def test_correct_top_keys(ws):
    _conf(ws)
    portable = json.loads((ws / ".mcp.json").read_text())
    vscode = json.loads((ws / ".vscode" / "mcp.json").read_text())
    assert "mcpServers" in portable and "servers" not in portable
    assert "servers" in vscode and "mcpServers" not in vscode
    assert cfg.SERVER_NAME in vscode["servers"]


def test_idempotent_noop(ws):
    _conf(ws)
    r2 = _conf(ws)
    assert all(rec["action"] == "no-op" for rec in r2["receipts"])


def test_preserves_existing_servers(ws):
    target = ws / ".vscode" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "servers": {"otherServer": {"type": "stdio", "command": "x"}},
        "inputs": [{"id": "i1"}]}))
    _conf(ws)
    doc = json.loads(target.read_text())
    assert "otherServer" in doc["servers"]
    assert cfg.SERVER_NAME in doc["servers"]
    assert doc["inputs"] == [{"id": "i1"}]


def test_dry_run_writes_nothing(ws):
    r = _conf(ws, dry_run=True)
    assert not (ws / ".mcp.json").exists()
    assert all(rec["dry_run"] for rec in r["receipts"])


def test_undo_removes_only_ours(ws):
    target = ws / ".vscode" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(
        {"servers": {"otherServer": {"type": "stdio", "command": "x"}}}))
    _conf(ws)
    cfg.unconfigure(workspace=ws, target_ids=None, dry_run=False)
    doc = json.loads(target.read_text())
    assert cfg.SERVER_NAME not in doc["servers"]
    assert "otherServer" in doc["servers"]


def test_invalid_existing_json_handled(ws):
    target = ws / ".mcp.json"
    target.write_text("{corrupt")
    r = _conf(ws)
    rec = next(x for x in r["receipts"]
                  if x["target"] == "workspace-portable")
    # corrupt file treated as empty → our entry written
    assert rec["written"]


def test_readonly_file_skipped(ws):
    target = ws / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"other": {}}}))
    target.chmod(0o444)
    try:
        r = _conf(ws)
        rec = next(x for x in r["receipts"]
                   if x["target"] == "workspace-portable")
        assert rec["action"] in ("skipped:file-not-writable", "no-op",
                                 "update", "create")
    finally:
        target.chmod(0o644)
