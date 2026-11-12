"""MCP tool implementations (stdlib-only, read-only)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import context as _context
from . import github as _github
from . import health as _health
from . import workspace as _workspace

Handler = Callable[[dict[str, Any], Any], dict[str, Any]]

HANDLERS: dict[str, Handler] = {
    "forge_health": _health.run,
    "forge_workspace_summary": _workspace.summary,
    "forge_architecture_review": _workspace.architecture_review,
    "forge_context_read": _context.context_read,
    "forge_rules_read": _context.rules_read,
    "forge_git_status": _github.git_status,
    "forge_gh_pr_read": _github.gh_pr_read,
}
