"""forge_health — honest component/dependency inventory (stdlib-only)."""

from __future__ import annotations

import shutil
import sys
from typing import Any

from .. import (
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    SUPPORTED_VERSIONS,
)


def _dep_state() -> dict[str, str]:
    """Importability of optional runtime deps — observed, never assumed."""
    out = {}
    for mod in ("pydantic", "typer", "yaml"):
        try:
            __import__(mod)
            out[mod] = "available"
        except ImportError:
            out[mod] = "unavailable:import-failed"
        except Exception as e:  # noqa: BLE001 — broken installs happen
            out[mod] = f"error:{type(e).__name__}"
    return out


def _component_inventory(ctx: Any) -> dict[str, Any]:
    gh = shutil.which("gh")
    git = shutil.which("git")
    state_dir = ctx.state_dir
    return {
        "python": {"state": "ready",
                   "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                   "executable": sys.executable},
        "git": {"state": "ready" if git else "unavailable:not-on-path",
                "path": git},
        "gh": {"state": "ready" if gh else "unavailable:not-on-path",
               "path": gh,
               "note": "auth verified only at call time via `gh auth status`"},
        "bridge_state_dir": {
            "state": "ready" if state_dir and state_dir.is_dir()
            else "unverified:not-initialized",
            "path": str(state_dir) if state_dir else None},
        "dependencies": _dep_state(),
    }


def run(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
    comps = _component_inventory(ctx)
    unavailable = {
        k: v.get("state") for k, v in comps.items()
        if isinstance(v, dict) and str(v.get("state", "")).startswith("unavailable")
    }
    unavailable.update(
        {f"dependency:{k}": v for k, v in comps["dependencies"].items()
         if v != "available"})
    return {
        "server": MCP_SERVER_NAME,
        "version": MCP_SERVER_VERSION,
        "protocol": {
            "supported_revisions": list(SUPPORTED_VERSIONS),
            "negotiated": ctx.negotiated_version,
            "era": ctx.era or "unnegotiated",
        },
        "profile": ctx.policy.profile,
        "policy": {
            "git_tools": "enabled" if ctx.policy.allow_git else "disabled",
            "gh_tools": "enabled" if ctx.policy.allow_gh else "disabled",
            "mutable_tools": "none-exist",
        },
        "workspace": {
            "root": str(ctx.guard.root) if ctx.guard else None,
            "authorized": ctx.guard is not None,
        },
        "components": comps,
        "unavailable": unavailable,
        "status": "ready" if ctx.guard else "restricted:no-workspace",
        "audit": {"enabled": ctx.audit.enabled,
                  "error": ctx.audit.error},
    }
