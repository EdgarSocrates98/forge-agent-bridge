"""MCP audit events (stdlib-only).

Append-only JSONL under the bridge state dir — minimized fields only:
timestamp, correlation id, event name, tool, outcome, duration, policy,
deny reason. Content payloads (prompts, file bodies, PR text) are never
written here.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

EVENT_NAMES = frozenset({
    "mcp.server.started", "mcp.server.stopped",
    "mcp.client.connected", "mcp.tool.discovered",
    "mcp.tool.called", "mcp.tool.completed",
    "mcp.tool.denied", "mcp.tool.failed",
    "mcp.policy.evaluated", "mcp.workspace.validated",
    "mcp.config.generated", "mcp.config.updated",
})

_lock = threading.Lock()


def default_audit_path(state_dir: Path | None = None) -> Path:
    sd = state_dir or Path(os.environ.get(
        "FAB_STATE_DIR", Path.home() / ".forge-bridge"))
    return sd / "mcp_audit.jsonl"


class McpAudit:
    """Minimal, append-only audit sink. Fail-open: audit failure never
    breaks a tool call (it degrades to a no-op sink with an error flag)."""

    def __init__(self, path: Path | None = None, *,
                 enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled and path is not None
        self.correlation = uuid.uuid4().hex[:12]
        self.error: str | None = None

    def emit(self, event: str, *, tool: str = "", outcome: str = "",
             duration_ms: float | None = None, policy: str = "",
             deny_reason: str = "", **fields: Any) -> None:
        if not self.enabled:
            return
        if event not in EVENT_NAMES:
            return
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "seq_correlation": self.correlation,
            "event": event,
        }
        if tool:
            rec["tool"] = tool
        if outcome:
            rec["outcome"] = outcome
        if duration_ms is not None:
            rec["duration_ms"] = round(duration_ms, 2)
        if policy:
            rec["policy"] = policy
        if deny_reason:
            rec["deny_reason"] = deny_reason
        for k, v in fields.items():
            if isinstance(v, (str, int, float, bool)) and k not in rec:
                rec[k] = v
        try:
            with _lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        except OSError as e:
            self.error = f"audit-write-failed:{type(e).__name__}"
