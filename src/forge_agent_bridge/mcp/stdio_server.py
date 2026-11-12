"""MCP stdio transport — newline-delimited JSON-RPC over stdin/stdout.

Rules of the channel:
- stdout carries ONLY JSON-RPC messages (one per line, UTF-8).
- everything else (logs, diagnostics, tracebacks) goes to stderr.
- no banners, no prompts, no CLI decoration.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path
from typing import TextIO

from .audit import McpAudit, default_audit_path
from .dispatcher import Dispatcher, ServerContext
from .protocol import parse_line
from .security import policy_for, resolve_profile
from .workspace import WorkspaceDenied, WorkspaceGuard, detect_workspace

_log = logging.getLogger("forge_agent_bridge.mcp")
_STOP = False


def _state_dir() -> Path:
    return Path(os.environ.get("FAB_STATE_DIR",
                              Path.home() / ".forge-bridge"))


def build_server(profile: str | None, workspace: str | None, *,
                 allow_git: bool | None, allow_gh: bool | None,
                 state_dir: Path | None = None,
                 audit: McpAudit | None = None) -> Dispatcher:
    prof = resolve_profile(profile)
    policy = policy_for(prof, allow_git=allow_git, allow_gh=allow_gh)
    ws = detect_workspace(workspace)
    guard = WorkspaceGuard(ws) if ws else None
    sd = state_dir or _state_dir()
    audit = audit or McpAudit(default_audit_path(sd))
    ctx = ServerContext(policy=policy, guard=guard,
                        state_dir=sd, audit=audit)
    disp = Dispatcher(ctx)
    audit.emit("mcp.server.started", policy=policy.profile,
               workspace=str(ws) if ws else "",
               outcome="ready" if guard else "restricted:no-workspace")
    if guard:
        audit.emit("mcp.workspace.validated", outcome="ok",
                   workspace=str(guard.root))
    return disp


def serve(disp: Dispatcher, *, stdin=None, stdout=None) -> int:
    """Read→dispatch→write loop. Returns process exit code."""
    global _STOP
    _STOP = False
    inp = stdin if stdin is not None else sys.stdin.buffer
    out = stdout if stdout is not None else sys.stdout.buffer
    max_bytes = disp.ctx.policy.max_message_bytes

    def _sigterm(_sig, _frm):
        global _STOP
        _STOP = True
    try:
        signal.signal(signal.SIGTERM, _sigterm)
    except (ValueError, OSError, AttributeError):
        pass  # non-main thread / platform without SIGTERM

    while not _STOP:
        try:
            raw = inp.readline()
        except OSError:
            break
        if not raw:
            break  # EOF — clean shutdown
        line = raw.strip()
        if not line:
            continue
        msg, err = parse_line(line, max_bytes=max_bytes)
        if err is not None:
            _write(out, err)
            continue
        resp = disp.handle(msg)
        if resp is not None:
            _write(out, resp)
    disp.ctx.audit.emit("mcp.server.stopped",
                        outcome="eof" if not _STOP else "sigterm")
    return 0


def _write(out, msg: dict) -> None:
    import json
    try:
        out.write(json.dumps(msg, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8") + b"\n")
        out.flush()
    except (OSError, BrokenPipeError):
        pass


def main(argv: list[str] | None = None,
         stdin: TextIO | None = None, stdout=None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        prog="forge_agent_bridge.mcp",
        description="Forge Agent Bridge — native MCP stdio server")
    ap.add_argument("--profile", default=None,
                    help="security profile: corporate-readonly|local-readonly|standard")
    ap.add_argument("--workspace", default=None,
                    help="authorized workspace root (defaults: FAB_MCP_WORKSPACE|cwd)")
    ap.add_argument("--allow-git", action="store_true", default=None,
                    help="enable read-only git tools")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--allow-gh", action="store_true", default=None,
                    help="enable gh-backed read tools (requires auth+allowlist)")
    ap.add_argument("--state-dir", default=None)
    args = ap.parse_args(argv)
    allow_git = False if args.no_git else (True if args.allow_git else None)
    try:
        disp = build_server(
            args.profile, args.workspace,
            allow_git=allow_git, allow_gh=args.allow_gh,
            state_dir=Path(args.state_dir) if args.state_dir else None)
    except WorkspaceDenied as e:
        print(f"mcp workspace denied: {e.reason}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"mcp configuration error: {e}", file=sys.stderr)
        return 2
    return serve(disp)


if __name__ == "__main__":
    raise SystemExit(main())
