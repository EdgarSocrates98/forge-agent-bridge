"""Request dispatch — dual-era method routing + tool invocation.

Era selection per connection (stdio process):
- ``initialize``          → legacy handshake (<= 2025-11-25 semantics)
- ``server/discover``     → modern (2026-07-28), also valid pre-anything
- requests carrying modern ``_meta`` version → served statelessly
- other requests          → need an established legacy session

The dispatcher never executes a tool call itself; it applies schema +
policy checks and invokes the registered handler.
"""

from __future__ import annotations

import json
import time
import traceback
from typing import Any

from . import (
    LATEST_LEGACY,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    META_PROTOCOL_VERSION,
    META_SERVER_INFO,
    SUPPORTED_LEGACY,
    SUPPORTED_MODERN,
    SUPPORTED_VERSIONS,
)
from . import protocol as P
from .audit import McpAudit
from .security import Policy
from .tool_registry import get_tool, list_tools, validate_args
from .tools import HANDLERS
from .workspace import WorkspaceDenied, WorkspaceGuard


class ServerContext:
    """Per-process server state handed to tools."""

    def __init__(self, *, policy: Policy, guard: WorkspaceGuard | None,
                 state_dir: Any, audit: McpAudit) -> None:
        self.policy = policy
        self.guard = guard
        self.state_dir = state_dir
        self.audit = audit
        self.era: str | None = None          # "legacy" | "modern" | None
        self.negotiated_version: str | None = None
        self.legacy_initialized = False
        self.client_info: dict[str, Any] | None = None


class Dispatcher:
    def __init__(self, ctx: ServerContext) -> None:
        self.ctx = ctx

    # -- entry point ----------------------------------------------------------

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """One message → response dict, or None for notifications/responses."""
        if P.is_notification(msg):
            return None  # notifications are never answered
        if not P.is_request(msg):
            # a response or malformed — no reply (avoids reply loops)
            return None
        mid = msg.get("id")
        method = msg.get("method", "")
        try:
            return self._route(mid, method, msg)
        except Exception:  # noqa: BLE001 — last-resort guard, logged to stderr
            traceback.print_exc()
            return P.make_error(mid, P.INTERNAL_ERROR,
                                "internal server error")

    # -- routing ----------------------------------------------------------------

    def _route(self, mid: Any, method: str,
               msg: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        # ---- era-defining methods ------------------------------------------
        if method == "initialize":
            return self._initialize(mid, msg)
        if method == "server/discover":
            return self._discover(mid, msg)

        # ---- modern path: any request may carry per-request _meta ----------
        req_v = P.requested_version(msg)
        if req_v is not None:
            if not P.version_supported(req_v, SUPPORTED_MODERN):
                return P.unsupported_version(mid, req_v)
            ctx.era = "modern"
            ctx.negotiated_version = req_v
            return self._modern(mid, method, msg)

        # ---- legacy path: requires completed handshake ----------------------
        if ctx.era == "legacy" and ctx.legacy_initialized:
            return self._legacy(mid, method, msg)

        # ---- ambiguous: no handshake, no _meta → fail closed ---------------
        if method in ("ping",):
            # bare ping tolerated only inside a negotiated legacy session
            return P.make_error(mid, P.INVALID_REQUEST,
                                "no protocol session established")
        return P.unsupported_version(mid, req_v or "unspecified")

    # -- legacy era -----------------------------------------------------------

    def _initialize(self, mid: Any, msg: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        params = msg.get("params") or {}
        proposed = params.get("protocolVersion")
        if isinstance(proposed, str) and proposed in SUPPORTED_LEGACY:
            chosen = proposed
        elif isinstance(proposed, str) and proposed in SUPPORTED_MODERN:
            # client proposed only modern on a legacy handshake → refuse
            return P.unsupported_version(mid, proposed)
        else:
            chosen = LATEST_LEGACY
        ctx.era = "legacy"
        ctx.negotiated_version = chosen
        ctx.legacy_initialized = True
        ci = params.get("clientInfo")
        if isinstance(ci, dict):
            ctx.client_info = {"name": str(ci.get("name", ""))[:80],
                               "version": str(ci.get("version", ""))[:40]}
        self.ctx.audit.emit("mcp.client.connected",
                            outcome="legacy",
                            client=str((ctx.client_info or {}).get("name", "")))
        return P.make_result(mid, {
            "protocolVersion": chosen,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": MCP_SERVER_NAME,
                           "version": MCP_SERVER_VERSION},
            "instructions": (
                "Forge Agent Bridge read-only tools. Profile: "
                f"{self.ctx.policy.profile}."),
        })

    def _legacy(self, mid: Any, method: str,
                msg: dict[str, Any]) -> dict[str, Any]:
        if method == "ping":
            return P.make_result(mid, {})
        if method == "tools/list":
            self.ctx.audit.emit("mcp.tool.discovered",
                                outcome=str(len(list_tools())))
            return P.make_result(mid, {"tools": list_tools()})
        if method == "tools/call":
            return self._call_tool(mid, msg)
        return P.make_error(mid, P.METHOD_NOT_FOUND,
                            f"unknown method: {method}")

    # -- modern era ------------------------------------------------------------

    def _discover(self, mid: Any, msg: dict[str, Any]) -> dict[str, Any]:
        self.ctx.era = "modern"
        self.ctx.negotiated_version = SUPPORTED_MODERN[0]
        return P.make_result(mid, {
            "resultType": "complete",
            "supportedVersions": list(SUPPORTED_VERSIONS),
            "capabilities": {"tools": {}},
            META_PROTOCOL_VERSION: SUPPORTED_MODERN[0],
            "_meta": {META_SERVER_INFO: {
                "name": MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION}},
            "instructions": (
                "Forge Agent Bridge read-only tools. Profile: "
                f"{self.ctx.policy.profile}."),
            "ttlMs": 3600000,
            "cacheScope": "public",
        })

    def _modern(self, mid: Any, method: str,
                msg: dict[str, Any]) -> dict[str, Any]:
        if method == "tools/list":
            self.ctx.audit.emit("mcp.tool.discovered",
                                outcome=str(len(list_tools())))
            res = {"tools": list_tools()}
            res["_meta"] = {META_SERVER_INFO: {
                "name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION}}
            return P.make_result(mid, res)
        if method == "tools/call":
            return self._call_tool(mid, msg)
        if method == "ping":
            # ping was removed in the modern revision — method unknown
            return P.make_error(mid, P.METHOD_NOT_FOUND,
                                "ping not supported in this revision")
        return P.make_error(mid, P.METHOD_NOT_FOUND,
                            f"unknown method: {method}")

    # -- tools ------------------------------------------------------------------

    def _call_tool(self, mid: Any, msg: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        params = msg.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str):
            return P.make_error(mid, P.INVALID_PARAMS,
                                "tools/call requires a string 'name'")
        t0 = time.monotonic()
        tool = get_tool(name)
        if tool is None:
            ctx.audit.emit("mcp.tool.denied", tool=name,
                           outcome="denied", deny_reason="unknown-tool",
                           policy=ctx.policy.profile)
            return P.make_error(mid, P.INVALID_PARAMS,
                                f"unknown tool: {name}")
        ok, reason = ctx.policy.tool_allowed(name)
        ctx.audit.emit("mcp.policy.evaluated", tool=name,
                       outcome="allow" if ok else "deny",
                       deny_reason=reason, policy=ctx.policy.profile)
        if not ok:
            ctx.audit.emit("mcp.tool.denied", tool=name, outcome="denied",
                           deny_reason=reason, policy=ctx.policy.profile)
            return P.make_error(mid, P.TOOL_DENIED,
                                f"tool denied by policy: {reason}",
                                {"tool": name, "reason": reason})
        valid, why = validate_args(name, params.get("arguments"))
        if not valid:
            return P.make_error(mid, P.INVALID_PARAMS, why)
        handler = HANDLERS.get(name)
        if handler is None:
            return P.make_error(mid, P.INTERNAL_ERROR,
                                f"tool registered without handler: {name}")
        ctx.audit.emit("mcp.tool.called", tool=name,
                       policy=ctx.policy.profile)
        try:
            out = handler(params.get("arguments") or {}, ctx)
        except WorkspaceDenied as e:
            ctx.audit.emit("mcp.tool.denied", tool=name, outcome="denied",
                           deny_reason=e.reason, policy=ctx.policy.profile)
            return P.make_error(mid, P.WORKSPACE_DENIED,
                                f"workspace denied: {e.reason}",
                                {"tool": name, "reason": e.reason})
        except Exception as e:  # noqa: BLE001 — tool failure is data, not crash
            ctx.audit.emit("mcp.tool.failed", tool=name,
                           outcome="failed",
                           deny_reason=type(e).__name__,
                           policy=ctx.policy.profile)
            return P.make_result(mid, {
                "isError": True,
                "content": [{"type": "text", "text":
                             f"tool execution failed: {type(e).__name__}"}],
            })
        dur = (time.monotonic() - t0) * 1000
        ctx.audit.emit("mcp.tool.completed", tool=name, outcome="ok",
                       duration_ms=dur, policy=ctx.policy.profile)
        # honest output cap — never return unbounded payloads
        text = json.dumps(out, ensure_ascii=False, default=str)
        cap = ctx.policy.max_response_bytes
        truncated = False
        if len(text.encode("utf-8")) > cap:
            text = text.encode("utf-8")[:cap].decode("utf-8", "replace")
            truncated = True
        result: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "structuredContent": out,
            "isError": False,
        }
        if truncated:
            result["content"][0]["text"] += "\n[truncated: response cap]"
        return P.make_result(mid, result)
