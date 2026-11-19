"""MCP diagnostics — ``forge-bridge mcp doctor`` checks (stdlib-only).

Every check reports an honest state: ready | unverified | unavailable |
restricted | requires-approval | error. A running process never equals
"ready" — verification means the check itself passed.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import MCP_SERVER_NAME, MCP_SERVER_VERSION, SUPPORTED_VERSIONS
from . import config as cfg
from .config import targets
from .security import resolve_profile
from .tool_registry import list_tools
from .workspace import WorkspaceDenied, WorkspaceGuard, detect_workspace


def _check(name: str, state: str, detail: str = "") -> dict[str, Any]:
    return {"check": name, "state": state, "detail": detail}


def _declared_entry_state(entry: Any) -> tuple[str, str]:
    """Validate a configured ``mcpServers``/``servers`` entry — §9.3 MCP
    health: the declared config must actually be able to start our server.

    ``error``      — structurally wrong (not an object, non-stdio type,
                     args that don't launch the bridge module, unknown
                     profile, absolute command path that does not exist).
    ``unverified`` — plausible but unprovable here (bare command name not
                     on this PATH — the host may resolve differently;
                     PYTHONPATH dir absent on this machine).
    ``ready``      — every declared field verified against this machine.
    """
    if not isinstance(entry, dict):
        return "error", "entry is not an object"
    problems: list[str] = []
    unverified: list[str] = []
    etype = entry.get("type")
    if etype is not None and etype != "stdio":
        problems.append(f"type {etype!r} != 'stdio'")
    cmd = entry.get("command")
    if not isinstance(cmd, str) or not cmd:
        problems.append("missing/invalid command")
    else:
        if os.path.isabs(cmd) or os.sep in cmd or (os.altsep and os.altsep in cmd):
            if not Path(cmd).is_file():
                problems.append(f"declared command {cmd!r} does not exist")
        elif shutil.which(cmd) is None:
            unverified.append(
                f"command {cmd!r} not on this PATH — host may resolve "
                "differently")
    args = entry.get("args")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        problems.append("missing/invalid args")
    else:
        module_entry = "forge_agent_bridge.mcp" in args
        cli_entry = (isinstance(cmd, str)
                     and Path(cmd).name.startswith("forge-bridge")
                     and args[:2] == ["mcp", "serve"])
        if not (module_entry or cli_entry):
            problems.append("args do not launch the bridge MCP module")
        elif "--profile" in args:
            try:
                resolve_profile(args[args.index("--profile") + 1])
            except (ValueError, IndexError):
                problems.append("declared --profile is not a known profile")
        env = entry.get("env")
        if isinstance(env, dict):
            pp = env.get("PYTHONPATH")
            if isinstance(pp, str) and pp and not Path(pp).is_dir():
                unverified.append(
                    f"env.PYTHONPATH {pp!r} absent on this machine")
    if problems:
        return "error", "; ".join(problems)
    if unverified:
        return "unverified", "; ".join(unverified)
    return "ready", "declared entry verified (command/args/profile)"


def _config_check(t) -> dict[str, Any]:
    """One ``config:<target-id>`` check — presence *and* declared-entry
    health, honest about what cannot be proven from this machine."""
    if not t.path.is_file():
        return _check(f"config:{t.id}", "unverified", f"{t.path} absent")
    try:
        doc = json.loads(t.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _check(f"config:{t.id}", "error",
                      f"unreadable: {type(e).__name__}")
    servers = doc.get(t.top_key)
    if cfg.SERVER_NAME not in (servers or {}):
        return _check(f"config:{t.id}", "unverified",
                      f"{t.path} (no entry)")
    state, detail = _declared_entry_state(servers[cfg.SERVER_NAME])
    return _check(f"config:{t.id}", state, f"{t.path} — {detail}")


def doctor(*, profile: str | None, workspace: str | None,
           state_dir: Path | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    ok = True

    v = sys.version_info
    py_ok = v >= (3, 11)
    ok &= py_ok
    checks.append(_check(
        "python-runtime", "ready" if py_ok else "error",
        f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"))

    try:
        prof = resolve_profile(profile)
        checks.append(_check("security-profile", "ready", prof))
    except ValueError as e:
        ok = False
        checks.append(_check("security-profile", "error", str(e)))
        prof = None

    checks.append(_check("protocol-revisions", "ready",
                         ",".join(SUPPORTED_VERSIONS)))
    checks.append(_check("tool-registry", "ready",
                         f"{len(list_tools())} tools: "
                         + ",".join(t["name"] for t in list_tools())))

    ws = detect_workspace(workspace)
    if ws is None:
        checks.append(_check("workspace", "unavailable",
                             "no authorized workspace root"))
    else:
        try:
            WorkspaceGuard(ws)
            checks.append(_check("workspace", "ready", str(ws)))
        except WorkspaceDenied as e:
            ok = False
            checks.append(_check("workspace", "restricted", e.reason))

    git = shutil.which("git")
    checks.append(_check(
        "git-binary", "ready" if git else "unverified",
        git or "not on PATH — git tools report unavailable"))
    gh = shutil.which("gh")
    if not gh:
        checks.append(_check("gh-binary", "unverified",
                             "not on PATH — gh tools report unavailable"))
    else:
        checks.append(_check("gh-binary", "ready", gh))

    sd = state_dir or Path(os.environ.get(
        "FAB_STATE_DIR", Path.home() / ".forge-bridge"))
    checks.append(_check(
        "bridge-state", "ready" if sd.is_dir() else "unverified",
        str(sd)))

    entry = shutil.which("forge-bridge")
    checks.append(_check(
        "cli-entrypoint", "ready" if entry else "unverified",
        entry or "forge-bridge not on PATH — module entry works via "
        "`python -m forge_agent_bridge.mcp`"))

    ws_path = Path(ws) if ws else None
    for t in targets(ws_path):
        checks.append(_config_check(t))
        if checks[-1]["state"] == "error":
            ok = False

    overall = "ready" if ok and all(
        c["state"] in ("ready", "unverified") for c in checks) else \
        ("error" if not ok else "restricted")
    return {"server": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION,
            "overall": overall, "checks": checks}
