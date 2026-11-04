"""GitHub Copilot CLI adapter.

Uses the supported non-interactive ``copilot -p`` surface. Authentication is
still owned by Copilot: a first-use auth failure is surfaced as FAB-AUTH and
never converted into a successful fake response.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from typing import Any, ClassVar

from ..adapter import AuthenticationError, ProviderUnavailableError, SessionError
from ..contracts import AgentSession, AuthState, ProviderDescriptor, SessionState, new_id


class CopilotAdapter:
    EXE = "copilot"
    SPAWN_ARGV: ClassVar[list[str]] = ["copilot"]

    def __init__(self) -> None:
        self.sessions: dict[str, AgentSession] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}

    def detect(self) -> ProviderDescriptor:
        return next((d for d in self._detect_all() if d.id == "github-copilot"),
                    ProviderDescriptor(id="github-copilot", name="GitHub Copilot CLI",
                                      kind="cli-jsonl", auth_state=AuthState.UNAUTHENTICATED))

    @staticmethod
    def _detect_all() -> list[ProviderDescriptor]:
        from ..registry import REGISTRY
        return REGISTRY.detect_all()

    def get_version(self) -> str | None:
        if not shutil.which(self.EXE):
            return None
        try:
            p = subprocess.run([self.EXE, "--version"], capture_output=True, text=True,
                               timeout=10, check=False)
            return p.stdout.strip().splitlines()[0] or None
        except OSError:
            return None

    def get_auth_status(self) -> str:
        return AuthState.UNVERIFIED.value if shutil.which(self.EXE) else AuthState.UNAUTHENTICATED.value

    def initialize(self) -> None:
        if not shutil.which(self.EXE):
            raise ProviderUnavailableError("copilot not on PATH", provider="github-copilot")

    def create_session(self, **kw: Any) -> AgentSession:
        self.initialize()
        s = AgentSession(id=new_id("ses"), provider="github-copilot",
                         model=kw.get("model"),
                         product_id=kw.get("product_id"), workspace_id=kw.get("workspace_id"),
                         state=SessionState.ACTIVE, resumable=False)
        self.sessions[s.id] = s
        self.events[s.id] = []
        return s

    def resume_session(self, session_ref: str) -> AgentSession:
        raise SessionError("FAB-UNSUPPORTED", "Copilot session resume requires a named CLI session",
                           provider="github-copilot")

    def list_sessions(self) -> list[AgentSession]:
        return list(self.sessions.values())

    def send_prompt(self, session_id: str, prompt: str,
                    attachments: list[dict[str, Any]] | None = None) -> None:
        if session_id not in self.sessions:
            raise SessionError("FAB-SESSION", f"unknown session {session_id}", provider="github-copilot")
        if attachments:
            raise SessionError("FAB-UNSUPPORTED", "attachments are not supported by Copilot CLI",
                               provider="github-copilot")
        try:
            cmd = [self.EXE, "-p", prompt, "--silent", "--allow-all-tools"]
            if self.sessions[session_id].model and self.sessions[session_id].model != "default":
                cmd += ["--model", self.sessions[session_id].model]
            p = subprocess.run(cmd,
                               capture_output=True, text=True, timeout=120, check=False)
        except FileNotFoundError as exc:
            raise ProviderUnavailableError("copilot not on PATH", provider="github-copilot") from exc
        if p.returncode != 0:
            detail = (p.stderr or p.stdout or "Copilot authentication or execution failed").strip()
            if "login" in detail.lower() or "auth" in detail.lower():
                raise AuthenticationError(detail[:400], provider="github-copilot")
            raise ProviderUnavailableError(detail[:400], provider="github-copilot")
        self.events[session_id] = [
            {"type": "content", "params": {"text": p.stdout.strip()}},
            {"type": "usage", "params": {"tokens_in": 0, "tokens_out": 0}},
        ]

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        if session_id not in self.sessions:
            raise SessionError("FAB-SESSION", f"unknown session {session_id}", provider="github-copilot")
        yield from self.events.pop(session_id, [])

    def respond_to_approval(self, approval_id: str, approved: bool) -> None:
        del approval_id, approved
        raise SessionError("FAB-UNSUPPORTED", "approval is handled by Copilot CLI", provider="github-copilot")

    def cancel(self, session_id: str) -> None:
        if session_id in self.sessions:
            self.sessions[session_id].state = SessionState.CLOSED

    def close_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            self.sessions[session_id].state = SessionState.CLOSED
        self.events.pop(session_id, None)

    def dispose(self) -> None:
        for sid in list(self.sessions):
            self.close_session(sid)


def copilot_adapter() -> CopilotAdapter:
    return CopilotAdapter()
