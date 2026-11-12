"""Security profiles and the per-operation policy engine (stdlib-only).

Profiles are *execution* policies for the MCP server — a separate axis
from install profiles (minimal/recommended/full):

- ``corporate-readonly``: strictest honest profile. Read-only tools only;
  no network-touching tools (``gh``) unless explicitly enabled; sensitive
  content stays out; subprocess use limited to read-only git. It is a
  *technical* restriction — it does not replace company authorization.
- ``local-readonly``: read-only tools; read-only git and ``gh`` queries
  are available when the binaries and auth genuinely verify.
- ``standard``: same read-only surface today — mutable tools do not exist
  yet; when they land they will gate behind explicit approval plumbing.

A profile NEVER silently upgrades: unknown names fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROFILES = ("corporate-readonly", "local-readonly", "standard")
DEFAULT_PROFILE = "corporate-readonly"

# Tools callable without spawning a subprocess at all.
_PURE_TOOLS = frozenset({
    "forge_health",
    "forge_workspace_summary",
    "forge_architecture_review",
    "forge_context_read",
    "forge_rules_read",
})
# Read-only but require spawning a binary (git).
_GIT_TOOLS = frozenset({"forge_git_status"})
# Read-only but require network + authenticated binary (gh).
_GH_TOOLS = frozenset({"forge_gh_pr_read"})

ALL_TOOLS = _PURE_TOOLS | _GIT_TOOLS | _GH_TOOLS


@dataclass(frozen=True)
class Policy:
    """Effective execution policy for one server process."""

    profile: str = DEFAULT_PROFILE
    allow_git: bool = False
    allow_gh: bool = False
    workspace_read_depth: int = 4
    max_scan_files: int = 600
    max_file_bytes: int = 256 * 1024
    max_response_bytes: int = 512 * 1024
    max_message_bytes: int = 4 * 1024 * 1024
    tool_timeout_s: float = 20.0
    extra: dict = field(default_factory=dict)

    def tool_allowed(self, name: str) -> tuple[bool, str]:
        """Effective decision for a tool call → (allowed, deny_reason)."""
        if name not in ALL_TOOLS:
            return False, "unknown-tool"
        if name in _GIT_TOOLS and not self.allow_git:
            return False, "git-tools-disabled-by-profile"
        if name in _GH_TOOLS and not self.allow_gh:
            return False, "gh-tools-disabled-by-profile"
        return True, ""


def policy_for(profile: str, *, allow_git: bool | None = None,
               allow_gh: bool | None = None) -> Policy:
    """Resolve a profile name → effective Policy. Unknown names fail closed."""
    p = (profile or DEFAULT_PROFILE).strip().lower()
    if p not in PROFILES:
        raise ValueError(f"unknown MCP security profile: {profile!r} "
                         f"(choose one of {', '.join(PROFILES)})")
    if p == "corporate-readonly":
        return Policy(
            profile=p,
            allow_git=True if allow_git is None else allow_git,
            allow_gh=False if allow_gh is None else allow_gh,
            workspace_read_depth=4, max_scan_files=600,
            max_file_bytes=256 * 1024, max_response_bytes=512 * 1024,
            tool_timeout_s=20.0)
    if p == "local-readonly":
        return Policy(
            profile=p,
            allow_git=True if allow_git is None else allow_git,
            allow_gh=True if allow_gh is None else allow_gh,
            workspace_read_depth=6, max_scan_files=1200,
            max_file_bytes=512 * 1024, max_response_bytes=1024 * 1024,
            tool_timeout_s=30.0)
    # standard — read-only surface today; mutable tools gate separately
    return Policy(
        profile=p,
        allow_git=True if allow_git is None else allow_git,
        allow_gh=True if allow_gh is None else allow_gh,
        workspace_read_depth=8, max_scan_files=2000,
        max_file_bytes=1024 * 1024, max_response_bytes=2 * 1024 * 1024,
        tool_timeout_s=45.0)


def resolve_profile(name: str | None, env: dict | None = None) -> str:
    """Profile resolution order: explicit flag > FAB_MCP_PROFILE env > default."""
    import os
    e = env if env is not None else os.environ
    p = (name or e.get("FAB_MCP_PROFILE") or DEFAULT_PROFILE).strip().lower()
    if p not in PROFILES:
        raise ValueError(f"unknown MCP security profile: {p!r}")
    return p
