"""Codex CLI adapter (§21.1) — `codex exec --json` per turn + `resume`.

Codex exec is a one-shot non-interactive run that emits JSONL events.
Multi-turn continuity is real: first turn captures `thread.started` →
thread_id; subsequent prompts run `codex exec resume <thread_id> --json`.
Sandbox defaults to `read-only` — approvals/escalation are honest named
states, never bypassed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

from ..adapter import (
    ProviderUnavailableError,
    SessionError,
    UnsupportedCapabilityError,
)
from ..contracts import AgentSession, SessionState, new_id


def _map_codex(ev: dict[str, Any]) -> dict[str, Any]:
    """codex exec JSONL event → bridge-native dict."""
    t = ev.get("type") or "unknown"
    if t == "thread.started":
        return {"type": "session/new",
                "params": {"native_id": ev.get("thread_id")}, "raw": ev}
    if t == "turn.started":
        return {"type": "turn_start", "params": {}, "raw": ev}
    if t in ("item.completed", "item.started", "item.updated"):
        item = ev.get("item") or {}
        it = item.get("type")
        if it == "agent_message":
            key = "content" if t == "item.completed" else "content_delta"
            return {"type": key, "params": {"text": item.get("text", "")},
                    "raw": ev}
        if it in ("command_execution", "mcp_tool_call", "file_change",
                  "web_search"):
            key = "tool_call" if t == "item.started" else "tool_result"
            return {"type": key,
                    "params": {"name": it,
                               "status": item.get("status"),
                               "detail": str(item.get("command")
                                            or item.get("changes") or "")[:400]},
                    "raw": ev}
        if it == "reasoning":
            return {"type": "content_delta",
                    "params": {"text": item.get("text", ""), "kind": "reasoning"},
                    "raw": ev}
        if it == "todo_list":
            return {"type": "plan_update",
                    "params": {"entries": item.get("items", [])}, "raw": ev}
        return {"type": "unknown", "params": {"native": it}, "raw": ev}
    if t == "turn.completed":
        usage = ev.get("usage") or {}
        return {"type": "usage", "params": {
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0)}, "raw": ev}
    if t in ("error", "turn.failed"):
        return {"type": "error",
                "params": {"message": str(ev.get("message") or ev)[:400]},
                "raw": ev}
    return {"type": "unknown", "params": {"native": t}, "raw": ev}


class CodexAdapter:
    """ProviderAdapter over `codex exec --json` — real per-turn processes
    with real resume via `codex exec resume <thread_id>`."""

    EXE = "codex"

    def __init__(self, sandbox: str = "read-only") -> None:
        self.sandbox = sandbox
        self._sessions: dict[str, AgentSession] = {}
        self._threads: dict[str, str] = {}          # session → codex thread_id
        self._turn_events: dict[str, list[dict[str, Any]]] = {}
        self._procs: dict[str, subprocess.Popen[bytes]] = {}

    def detect(self):
        from ..registry import REGISTRY
        return next((d for d in REGISTRY.detect_all() if d.id == "codex"), None)

    def get_version(self) -> str | None:
        exe = shutil.which(self.EXE)
        if not exe:
            return None
        try:
            out = subprocess.run([exe, "--version"], check=False, capture_output=True,
                                 text=True, timeout=10)
            return out.stdout.strip().splitlines()[0] or None
        except Exception:  # noqa: BLE001
            return None

    def get_auth_status(self) -> str:
        from ..contracts import AuthState
        return (AuthState.UNVERIFIED
                if shutil.which(self.EXE) else AuthState.UNAUTHENTICATED).value

    def initialize(self) -> None:
        if not shutil.which(self.EXE):
            raise ProviderUnavailableError("codex not on PATH", provider="codex")

    def create_session(self, **kw: Any) -> AgentSession:
        self.initialize()
        if kw.get("mcp_servers"):
            raise UnsupportedCapabilityError(
                "mcp_servers (use ~/.codex/config.toml)", provider="codex")
        s = AgentSession(id=new_id("ses"), provider="codex",
                         product_id=kw.get("product_id"),
                         workspace_id=kw.get("workspace_id"),
                         state=SessionState.ACTIVE, resumable=True)
        self._sessions[s.id] = s
        self._turn_events[s.id] = []
        return s

    def resume_session(self, session_ref: str) -> AgentSession:
        self.initialize()
        s = AgentSession(id=new_id("ses"), provider="codex",
                         state=SessionState.ACTIVE, resumable=True,
                         provider_session_ref=session_ref)
        self._sessions[s.id] = s
        self._threads[s.id] = session_ref
        self._turn_events[s.id] = []
        return s

    def list_sessions(self) -> list[AgentSession]:
        return list(self._sessions.values())

    def send_prompt(self, session_id: str, prompt: str,
                    attachments: list[dict[str, Any]] | None = None) -> None:
        s = self._sessions.get(session_id)
        if not s:
            raise SessionError("FAB-SESSION", f"unknown session {session_id}",
                               provider="codex")
        if attachments:
            raise UnsupportedCapabilityError("attachments", provider="codex")
        thread = self._threads.get(session_id)
        if thread:
            cmd = [self.EXE, "exec", "resume", thread, "--json", prompt]
        else:
            cmd = [self.EXE, "exec", "--json", "--sandbox", self.sandbox, prompt]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=False,
                start_new_session=True)
        except FileNotFoundError as exc:
            raise ProviderUnavailableError("codex not on PATH",
                                           provider="codex") from exc
        self._procs[session_id] = proc
        events: list[dict[str, Any]] = []
        assert proc.stdout
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "thread.started" and ev.get("thread_id"):
                self._threads[session_id] = str(ev["thread_id"])
                s.provider_session_ref = str(ev["thread_id"])
            events.append(ev)
        proc.wait(timeout=5)
        self._procs.pop(session_id, None)
        self._turn_events[session_id] = events

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        if session_id not in self._sessions:
            raise SessionError("FAB-SESSION", f"unknown session {session_id}",
                               provider="codex")
        for ev in self._turn_events.pop(session_id, []):
            yield _map_codex(ev)

    def respond_to_approval(self, approval_id: str, approved: bool) -> None:
        # codex exec is non-interactive; approvals are expressed via sandbox
        # policy — never auto-bypassed.
        raise UnsupportedCapabilityError("approvals", provider="codex")

    def cancel(self, session_id: str) -> None:
        proc = self._procs.get(session_id)
        if proc and proc.poll() is None:
            import contextlib
            import os
            import signal
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(proc.pid, signal.SIGTERM)

    def close_session(self, session_id: str) -> None:
        self.cancel(session_id)
        self._turn_events.pop(session_id, None)
        self._threads.pop(session_id, None)
        if session_id in self._sessions:
            self._sessions[session_id].state = SessionState.CLOSED

    def dispose(self) -> None:
        for sid in list(self._sessions):
            self.close_session(sid)


def codex_adapter() -> CodexAdapter:
    return CodexAdapter()
