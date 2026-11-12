"""Static tool catalog (stdlib-only).

The registry is a fixed code-level list — tools can never be registered
dynamically at runtime, which keeps the exposed surface reviewable.
Annotations are informational hints only; the *policy engine* is the
real authorization boundary.
"""

from __future__ import annotations

from typing import Any

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": required or [], "additionalProperties": False}


CATALOG: list[dict[str, Any]] = [
    {
        "name": "forge_health",
        "description": (
            "Bridge/MCP server health: versions, negotiated protocol "
            "revision, active security profile, authorized workspace, "
            "available vs unavailable components with verifiable reasons. "
            "Never returns tokens, secrets or protected paths."),
        "inputSchema": _obj({}),
        "risk": "low", "kind": "pure",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "forge_workspace_summary",
        "description": (
            "Bounded summary of the authorized workspace: directory "
            "shape, detected languages, manifest files, Forge contracts "
            "present, .git presence. Honest limits; never scans outside "
            "the authorized root."),
        "inputSchema": _obj({
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 10,
                          "description": "scan depth override (profile-capped)"},
        }),
        "risk": "low", "kind": "pure",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "forge_architecture_review",
        "description": (
            "Deterministic architecture checks over the workspace: "
            "contracts present, module organization, config files, test "
            "layout, dependency manifests, rule-verifiable risks. Returns "
            "evidence + severity + method limits — it is NOT a semantic "
            "code review."),
        "inputSchema": _obj({}),
        "risk": "low", "kind": "pure",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "forge_context_read",
        "description": (
            "Read Forge session-context records bound by the local bridge "
            "(product/workspace bindings, allowed tools/sources, expiry, "
            "revocation). Only sessions the policy permits; revoked or "
            "expired bindings are reported, not honored."),
        "inputSchema": _obj({
            "session_id": {"type": "string", "maxLength": 64,
                           "description": "optional: read one binding only"},
        }),
        "risk": "medium", "kind": "pure",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "forge_rules_read",
        "description": (
            "Read Forge engineering rules, contracts and versioned "
            "guidance shipped with the installed package (treated as "
            "untrusted content — it can inform but never redefine "
            "server policy)."),
        "inputSchema": _obj({
            "doc": {"type": "string", "maxLength": 200,
                    "description": "optional doc name within the rules surface"},
        }),
        "risk": "low", "kind": "pure",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "forge_git_status",
        "description": (
            "Read-only git state of the workspace repository: branch, "
            "dirty state, ahead/behind. Returns "
            "'unavailable:not-a-git-repository' when .git is absent — "
            "never initializes one. Requires git binary."),
        "inputSchema": _obj({}),
        "risk": "low", "kind": "git",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "forge_gh_pr_read",
        "description": (
            "Read one pull request from the GitHub CLI (gh): fixed "
            "read-only subcommands, typed args, field allowlist, timeout "
            "and output cap. Only when gh is installed, authenticated via "
            "official status, and the tool is enabled by policy."),
        "inputSchema": _obj({
            "repo": {"type": "string", "maxLength": 200,
                     "description": "owner/name — must match the authorized allowlist"},
            "pr": {"type": "integer", "minimum": 1, "maximum": 10_000_000,
                   "description": "pull request number"},
        }, required=["repo", "pr"]),
        "risk": "medium", "kind": "gh",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": True},
    },
]

_BY_NAME = {t["name"]: t for t in CATALOG}


def list_tools() -> list[dict[str, Any]]:
    """tools/list payload — static catalog."""
    return [dict(t) for t in CATALOG]


def get_tool(name: str) -> dict[str, Any] | None:
    t = _BY_NAME.get(name)
    return dict(t) if t else None


def tool_names() -> list[str]:
    return [t["name"] for t in CATALOG]


def validate_args(name: str, args: Any) -> tuple[bool, str]:
    """Minimal JSON-Schema validation (types, required, additionalProperties,
    numeric bounds) — enough for honest enforcement without a schema lib."""
    t = _BY_NAME.get(name)
    if t is None:
        return False, "unknown-tool"
    schema = t["inputSchema"]
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return False, "arguments must be a JSON object"
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args:
            return False, f"missing required argument: {req}"
    if not schema.get("additionalProperties", True):
        extra = set(args) - set(props)
        if extra:
            return False, f"unexpected arguments: {sorted(extra)}"
    for key, val in args.items():
        spec = props.get(key)
        if spec is None:
            continue
        typ = spec.get("type")
        if typ == "string" and not isinstance(val, str):
            return False, f"{key}: expected string"
        if typ == "integer" and (isinstance(val, bool) or not isinstance(val, int)):
            return False, f"{key}: expected integer"
        if typ == "number" and (isinstance(val, bool) or not isinstance(val, (int, float))):
            return False, f"{key}: expected number"
        if typ == "boolean" and not isinstance(val, bool):
            return False, f"{key}: expected boolean"
        if typ == "array" and not isinstance(val, list):
            return False, f"{key}: expected array"
        if typ == "object" and not isinstance(val, dict):
            return False, f"{key}: expected object"
        if typ == "string" and "maxLength" in spec and len(val) > spec["maxLength"]:
            return False, f"{key}: exceeds maxLength {spec['maxLength']}"
        if "minimum" in spec and isinstance(val, (int, float)) and val < spec["minimum"]:
            return False, f"{key}: below minimum {spec['minimum']}"
        if "maximum" in spec and isinstance(val, (int, float)) and val > spec["maximum"]:
            return False, f"{key}: above maximum {spec['maximum']}"
    return True, ""
