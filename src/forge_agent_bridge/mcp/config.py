"""MCP host configuration writers (stdlib-only).

Supported targets, per the real host contracts:
- ``~/.copilot/mcp-config.json``  — portable Copilot file (``mcpServers``);
  honors ``COPILOT_HOME`` when set.
- ``<workspace>/.mcp.json``        — workspace-level portable file (``mcpServers``).
- ``<workspace>/.vscode/mcp.json`` — VS Code managed format (``servers`` —
  NOT interchangeable with ``mcpServers``).

Writers preserve every other entry, are idempotent (our server name is
replaced, never duplicated), write atomically, keep a timestamped backup,
and never touch read-only/managed files to force a write.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVER_NAME = "forgeAgentBridge"


@dataclass
class ConfigTarget:
    id: str
    path: Path
    top_key: str        # "mcpServers" | "servers"
    scope: str


def copilot_home() -> Path:
    v = os.environ.get("COPILOT_HOME")
    return Path(v).expanduser() if v else Path.home() / ".copilot"


def targets(workspace: Path | None) -> list[ConfigTarget]:
    out = [ConfigTarget(
        "copilot-portable",
        copilot_home() / "mcp-config.json", "mcpServers", "user")]
    if workspace is not None:
        out.append(ConfigTarget(
            "workspace-portable", workspace / ".mcp.json",
            "mcpServers", "workspace"))
        out.append(ConfigTarget(
            "vscode-managed", workspace / ".vscode" / "mcp.json",
            "servers", "workspace"))
    return out


def server_block(*, python: str, workspace: str | None,
                 profile: str, tools: list[str] | None,
                 module_path: str | None = None) -> dict[str, Any]:
    """The mcpServers entry for our server — real, verified paths only."""
    args = ["-m", "forge_agent_bridge.mcp",
            "--profile", profile]
    if workspace:
        args += ["--workspace", workspace]
    block: dict[str, Any] = {"type": "stdio", "command": python, "args": args}
    if module_path:
        block["env"] = {"PYTHONPATH": module_path}
    if tools:
        block["tools"] = tools
    return block


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply(target: ConfigTarget, block: dict[str, Any], *,
          dry_run: bool, backup: bool) -> dict[str, Any]:
    """Insert/replace our entry in a target file → receipt dict."""
    path = target.path
    existed = path.is_file()
    doc = _read_json(path)
    servers = doc.get(target.top_key)
    if not isinstance(servers, dict):
        servers = {}
        doc[target.top_key] = servers
    already = SERVER_NAME in servers
    prev = servers.get(SERVER_NAME)
    changed = prev != block
    result = {
        "target": target.id, "path": str(path),
        "top_key": target.top_key, "existed": existed,
        "already_present": already, "changed": changed,
        "action": ("no-op" if already and not changed else
                   "update" if already else "create"),
    }
    if dry_run or not changed:
        result["dry_run"] = dry_run
        return result
    if existed and not os.access(path, os.W_OK):
        result.update({"action": "skipped:file-not-writable",
                       "note": "managed or read-only file left untouched"})
        return result
    servers[SERVER_NAME] = block
    if backup and existed:
        bpath = path.with_suffix(
            path.suffix + f".bak-{time.strftime('%Y%m%d%H%M%S')}")
        try:
            shutil.copy2(path, bpath)
            result["backup"] = str(bpath)
        except OSError as e:
            result["backup_error"] = type(e).__name__
    try:
        _atomic_write(path, doc)
        result["written"] = True
    except OSError as e:
        result.update({"written": False,
                       "error": f"{type(e).__name__}"})
    return result


def configure(*, python: str, workspace: Path | None, profile: str,
              tools: list[str] | None, target_ids: list[str] | None,
              dry_run: bool, backup: bool = True,
              module_path: str | None = None) -> dict[str, Any]:
    """Write our server entry into selected targets → receipts."""
    ws = str(workspace) if workspace else None
    block = server_block(python=python, workspace=ws, profile=profile,
                         tools=tools, module_path=module_path)
    receipts = []
    for t in targets(workspace):
        if target_ids and t.id not in target_ids:
            continue
        receipts.append(apply(t, block, dry_run=dry_run, backup=backup))
    return {"server": SERVER_NAME, "block": block, "receipts": receipts}


def unconfigure(*, workspace: Path | None,
                target_ids: list[str] | None, dry_run: bool) -> dict[str, Any]:
    """Remove ONLY our entry — preserves every other server and key."""
    receipts = []
    for t in targets(workspace):
        if target_ids and t.id not in target_ids:
            continue
        path = t.path
        doc = _read_json(path) if path.is_file() else {}
        servers = doc.get(t.top_key)
        present = isinstance(servers, dict) and SERVER_NAME in servers
        rec = {"target": t.id, "path": str(path), "present": present}
        if present and not dry_run:
            del servers[SERVER_NAME]
            _atomic_write(path, doc)
            rec["removed"] = True
        receipts.append(rec)
    return {"server": SERVER_NAME, "receipts": receipts}
