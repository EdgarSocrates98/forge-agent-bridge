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
        if t.path.is_file():
            try:
                doc = json.loads(t.path.read_text(encoding="utf-8"))
                has = cfg.SERVER_NAME in (doc.get(t.top_key) or {})
                checks.append(_check(
                    f"config:{t.id}", "ready" if has else "unverified",
                    f"{t.path} ({'configured' if has else 'no entry'})"))
            except (OSError, json.JSONDecodeError) as e:
                checks.append(_check(f"config:{t.id}", "error",
                                     f"unreadable: {type(e).__name__}"))
        else:
            checks.append(_check(f"config:{t.id}", "unverified",
                                 f"{t.path} absent"))

    overall = "ready" if ok and all(
        c["state"] in ("ready", "unverified") for c in checks) else \
        ("error" if not ok else "restricted")
    return {"server": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION,
            "overall": overall, "checks": checks}
