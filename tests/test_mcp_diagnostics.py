"""MCP registration health — ``forge-bridge mcp doctor`` validates the
*declared* server entry, not merely its presence (cycle-16.1 wave-08,
master prompt §9.3: "verificar a capacidade real de iniciar o servidor").

States: ``ready`` (declared command/args/profile verified here),
``unverified`` (plausible but unprovable from this machine),
``error`` (structurally unable to start our server).
"""

from __future__ import annotations

import json
import sys

import pytest

from forge_agent_bridge.mcp import config as cfg
from forge_agent_bridge.mcp import diagnostics


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / ".copilot"))
    return tmp_path


def _write(ws, target_file, top_key, entry):
    p = ws / target_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({top_key: {cfg.SERVER_NAME: entry}}))


def _config_state(doc, target):
    c = next(x for x in doc["checks"] if x["check"] == f"config:{target}")
    return c["state"], c["detail"]


def _doctor(ws, **kw):
    kw.setdefault("profile", None)
    kw.setdefault("workspace", str(ws))
    return diagnostics.doctor(**kw)


def test_absent_config_files_unverified(ws):
    doc = _doctor(ws)
    for target in ("copilot-portable", "workspace-portable",
                   "vscode-managed"):
        state, _ = _config_state(doc, target)
        assert state == "unverified"


def test_valid_declared_entry_ready(ws):
    entry = cfg.server_block(python=sys.executable, workspace=str(ws),
                             profile="corporate-readonly", tools=None)
    _write(ws, ".mcp.json", "mcpServers", entry)
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "ready", detail


def test_forge_bridge_cli_entry_accepted(ws):
    """`forge.json` declares mcp_command = forge-bridge mcp serve — a
    registered entry shaped that way is valid too."""
    (ws / "bin").mkdir()
    (ws / "bin" / "forge-bridge").write_text("#!shim")
    _write(ws, ".mcp.json", "mcpServers", {
        "type": "stdio",
        "command": str(ws / "bin" / "forge-bridge"),
        "args": ["mcp", "serve"]})
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "ready", detail


def test_bad_profile_is_error(ws):
    entry = cfg.server_block(python=sys.executable, workspace=str(ws),
                             profile="corporate-readonly", tools=None)
    entry["args"][entry["args"].index("--profile") + 1] = "bogus-profile"
    _write(ws, ".mcp.json", "mcpServers", entry)
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "error" and "profile" in detail
    assert doc["overall"] == "error"


def test_missing_absolute_command_is_error(ws):
    _write(ws, ".mcp.json", "mcpServers", {
        "type": "stdio", "command": "/no/such/python-xyz",
        "args": ["-m", "forge_agent_bridge.mcp"]})
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "error" and "does not exist" in detail


def test_bare_command_not_on_path_is_unverified(ws):
    """A bare command name unresolved here stays `unverified` — the host
    may spawn with a different PATH. Never a fake `ready`."""
    _write(ws, ".mcp.json", "mcpServers", {
        "type": "stdio", "command": "definitely-not-a-real-binary-xyz",
        "args": ["-m", "forge_agent_bridge.mcp"]})
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "unverified" and "PATH" in detail
    # unverified is an honest non-failure — overall is not `error`
    assert doc["overall"] != "error"


def test_args_not_launching_module_is_error(ws):
    _write(ws, ".vscode/mcp.json", "servers", {
        "type": "stdio", "command": sys.executable,
        "args": ["-m", "some.other.module"]})
    doc = _doctor(ws)
    state, detail = _config_state(doc, "vscode-managed")
    assert state == "error" and "bridge MCP module" in detail


def test_non_dict_entry_is_error(ws):
    _write(ws, ".mcp.json", "mcpServers", "forge-bridge mcp serve")
    doc = _doctor(ws)
    state, _detail = _config_state(doc, "workspace-portable")
    assert state == "error"


def test_file_without_our_entry_unverified(ws):
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"otherServer": {"command": "x"}}}))
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "unverified" and "no entry" in detail


def test_unreadable_config_is_error(ws):
    (ws / ".mcp.json").write_text("{corrupt")
    doc = _doctor(ws)
    state, detail = _config_state(doc, "workspace-portable")
    assert state == "error" and "unreadable" in detail
