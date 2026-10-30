"""Claude Code adapter (§21.2) — real bidirectional `stream-json` sessions.

Spawn: claude -p --verbose --output-format stream-json
            --input-format stream-json [--session-id <uuid>]
One long-lived process per bridge session; prompts are written as
stream-json user messages on stdin; stdout events are queued by a reader
thread and mapped to bridge-native event dicts.
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from collections.abc import Iterator
from typing import Any

from ..adapter import (
    ProviderUnavailableError,
    SessionError,
)
from ..contracts import AgentSession, SessionState, new_id


def _map_claude(ev: dict[str, Any]) -> dict[str, Any]:
    """claude stream-json event → bridge-native dict (§5.5 raw preserved)."""
    t = ev.get("type") or "unknown"
    if t == "stream_event":
        inner = ev.get("event") or {}
        it = inner.get("type")
        if it == "content_block_delta":
            delta = (inner.get("delta") or {}).get("text", "")
            return {"type": "content_delta", "params": {"text": delta}, "raw": ev}
        if it == "message_stop":
            return {"type": "content", "params": {}, "raw": ev}
        return {"type": "unknown", "params": {"native": it}, "raw": ev}
    if t == "assistant":
        blocks = (ev.get("message") or {}).get("content") or []
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        tools = [b.get("name", "tool") for b in blocks if b.get("type") == "tool_use"]
        if tools:
            return {"type": "tool_call",
                    "params": {"name": tools[0], "text": " ".join(texts)}, "raw": ev}
        return {"type": "content", "params": {"text": "\n".join(texts)}, "raw": ev}
    if t == "result":
        usage = ev.get("usage") or {}
        return {"type": "usage", "params": {
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
            "stop": ev.get("subtype")}, "raw": ev}
    if t == "control_request":
        return {"type": "request_permission",
                "params": {"approval_id": ev.get("request_id"),
                           "detail": json.dumps(ev.get("request", {}))[:400]},
                "raw": ev}
    if t in ("system", "user", "summary", "hook_started", "hook_response"):
        return {"type": "unknown", "params": {"native": t}, "raw": ev}
    return {"type": "unknown", "params": {"native": t}, "raw": ev}


class ClaudeAdapter:
    """ProviderAdapter over `claude -p --output-format stream-json
    --input-format stream-json` — real streaming session, per-session proc."""

    EXE = "claude"

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._queues: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._sessions: dict[str, AgentSession] = {}
        self._pending_approvals: dict[str, str] = {}  # approval_id → session_id

    def _reader(self, proc: subprocess.Popen[bytes],
                q: queue.Queue[dict[str, Any]]) -> None:
        assert proc.stdout
        for line in proc.stdout:
            try:
                q.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        q.put({"type": "__eof__"})

    def detect(self):
        from ..registry import REGISTRY
        return next((d for d in REGISTRY.detect_all() if d.id == "claude-code"),
                    None)

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
            raise ProviderUnavailableError("claude not on PATH",
                                           provider="claude-code")

    def _spawn(self, session_uuid: str, resume_ref: str | None,
               cwd: str) -> subprocess.Popen[bytes]:
        cmd = [self.EXE, "-p", "--verbose",
               "--output-format", "stream-json",
               "--input-format", "stream-json"]
        if resume_ref:
            cmd += ["--resume", resume_ref]
        else:
            cmd += ["--session-id", session_uuid]
        try:
            return subprocess.Popen(
                cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError as exc:
            raise ProviderUnavailableError("claude not on PATH",
                                           provider="claude-code") from exc

    def create_session(self, **kw: Any) -> AgentSession:
        self.initialize()
        import uuid
        s = AgentSession(id=new_id("ses"), provider="claude-code",
                         product_id=kw.get("product_id"),
                         workspace_id=kw.get("workspace_id"),
                         state=SessionState.ACTIVE, resumable=True)
        s.provider_session_ref = str(uuid.uuid4())
        proc = self._spawn(s.provider_session_ref, None, kw.get("cwd") or ".")
        q: queue.Queue[dict[str, Any]] = queue.Queue()
        self._procs[s.id] = proc
        self._queues[s.id] = q
        self._sessions[s.id] = s
        threading.Thread(target=self._reader, args=(proc, q), daemon=True).start()
        return s

    def resume_session(self, session_ref: str) -> AgentSession:
        self.initialize()
        s = AgentSession(id=new_id("ses"), provider="claude-code",
                         state=SessionState.ACTIVE, resumable=True,
                         provider_session_ref=session_ref)
        proc = self._spawn("", session_ref, ".")
        q: queue.Queue[dict[str, Any]] = queue.Queue()
        self._procs[s.id] = proc
        self._queues[s.id] = q
        self._sessions[s.id] = s
        threading.Thread(target=self._reader, args=(proc, q), daemon=True).start()
        return s

    def list_sessions(self) -> list[AgentSession]:
        return list(self._sessions.values())

    def send_prompt(self, session_id: str, prompt: str,
                    attachments: list[dict[str, Any]] | None = None) -> None:
        proc = self._procs.get(session_id)
        if not proc or not proc.stdin or proc.poll() is not None:
            raise SessionError("FAB-SESSION", f"session {session_id} not running",
                               provider="claude-code")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for a in attachments or []:
            if a.get("type") == "image" and a.get("data"):
                content.append({"type": "image", "source": a["data"]})
            else:
                content.append({"type": "text",
                                "text": f"[attachment:{a.get('path', '?')}]"})
        msg = {"type": "user",
               "message": {"role": "user", "content": content}}
        proc.stdin.write(json.dumps(msg).encode() + b"\n")
        proc.stdin.flush()

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        q = self._queues.get(session_id)
        if q is None:
            raise SessionError("FAB-SESSION", f"unknown session {session_id}",
                               provider="claude-code")
        # Non-blocking drain of everything queued so far.
        while True:
            try:
                ev = q.get_nowait()
            except queue.Empty:
                return
            if ev.get("type") == "__eof__":
                return
            if ev.get("type") == "control_request":
                rid = str(ev.get("request_id", ""))
                if rid:
                    self._pending_approvals[rid] = session_id
            yield _map_claude(ev)

    def respond_to_approval(self, approval_id: str, approved: bool) -> None:
        sid = self._pending_approvals.pop(approval_id, None)
        proc = self._procs.get(sid or "")
        if not proc or not proc.stdin:
            raise SessionError("FAB-SESSION", "no pending approval",
                               provider="claude-code")
        resp = {"type": "control_response",
                "response": {"request_id": approval_id,
                             "response": {"behavior": "allow" if approved
                                          else "deny"}}}
        proc.stdin.write(json.dumps(resp).encode() + b"\n")
        proc.stdin.flush()

    def cancel(self, session_id: str) -> None:
        # stream-json interrupt: send interrupt control request if supported;
        # honest fallback is closing stdin (ends the turn at next boundary).
        proc = self._procs.get(session_id)
        if proc and proc.stdin and proc.poll() is None:
            try:
                req = {"type": "control_request",
                       "request": {"subtype": "interrupt"}}
                proc.stdin.write(json.dumps(req).encode() + b"\n")
                proc.stdin.flush()
            except OSError:
                pass

    def close_session(self, session_id: str) -> None:
        proc = self._procs.pop(session_id, None)
        self._queues.pop(session_id, None)
        if session_id in self._sessions:
            self._sessions[session_id].state = SessionState.CLOSED
        if proc and proc.poll() is None:
            import contextlib
            import os
            import signal
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(proc.pid, signal.SIGTERM)

    def dispose(self) -> None:
        for sid in list(self._procs):
            self.close_session(sid)


def claude_adapter() -> ClaudeAdapter:
    return ClaudeAdapter()
