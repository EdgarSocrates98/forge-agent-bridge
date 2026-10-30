"""Fake provider — contract-test double (§19 testes).

Emits a deterministic native event stream so the full pipeline
(adapter → normalize → buffer → replay) is testable without any CLI.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import Any, ClassVar

from ..contracts import AgentSession, AuthState, ProviderDescriptor, SessionState, new_id


class FakeAdapter:
    # test stub: the fake provider has no binary; its
    # supervised process is a harmless sleeper (POSIX test surface)
    SPAWN_ARGV: ClassVar[list[str]] = ["sleep", "3600"]
    def __init__(self) -> None:
        self.sessions: dict[str, AgentSession] = {}
        self.prompts: dict[str, list[str]] = {}
        self.approvals: dict[str, bool] = {}
        self.cancelled: set[str] = set()
        self.initialized = False
        self._turn = itertools.count(1)

    def detect(self) -> ProviderDescriptor:
        return ProviderDescriptor(id="fake", name="Fake Provider", kind="fake",
                                  auth_state=AuthState.AUTHENTICATED)

    def get_version(self) -> str | None:
        return "fake/0.1"

    def get_auth_status(self) -> str:
        return AuthState.AUTHENTICATED.value

    def initialize(self) -> None:
        self.initialized = True

    def create_session(self, **kw: Any) -> AgentSession:
        s = AgentSession(id=new_id("ses"), provider="fake", resumable=True,
                         product_id=kw.get("product_id"),
                         workspace_id=kw.get("workspace_id"))
        s.state = SessionState.ACTIVE
        self.sessions[s.id] = s
        return s

    def resume_session(self, session_ref: str) -> AgentSession:
        s = self.sessions.get(session_ref)
        if not s:
            from ..adapter import SessionError
            raise SessionError("FAB-SESSION", f"unknown session {session_ref}")
        s.state = SessionState.ACTIVE
        return s

    def list_sessions(self) -> list[AgentSession]:
        return list(self.sessions.values())

    def send_prompt(self, session_id: str, prompt: str,
                    attachments: list[dict[str, Any]] | None = None) -> None:
        self.prompts.setdefault(session_id, []).append(prompt)

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        """Native (pre-normalization) event stream for the last prompt."""
        yield {"type": "session/new", "params": {"session_id": session_id}}
        for prompt in self.prompts.get(session_id, []):
            yield {"type": "prompt", "params": {"text": prompt}}
            yield {"type": "content_delta", "params": {"text": f"echo:{prompt}"}}
            yield {"type": "tool_call", "params": {"name": "noop"}}
            yield {"type": "tool_result", "params": {"name": "noop", "ok": True}}
            yield {"type": "content", "params": {"text": f"done:{prompt}"}}
            yield {"type": "usage", "params": {"tokens_in": 10, "tokens_out": 20}}

    def respond_to_approval(self, approval_id: str, approved: bool) -> None:
        self.approvals[approval_id] = approved

    def cancel(self, session_id: str) -> None:
        self.cancelled.add(session_id)

    def close_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            self.sessions[session_id].state = SessionState.CLOSED

    def dispose(self) -> None:
        self.sessions.clear()
        self.prompts.clear()
