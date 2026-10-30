"""ACP-backed provider adapter (§21) — real sessions over `agent acp`.

Generic over any CLI that speaks ACP on stdio (`devin acp`, and other
agents exposing the same mode). One spawned agent process per session —
process isolation matches the local-bridge supervisor model.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from typing import Any

from ..acp import AcpClient
from ..adapter import (
    BridgeError,
    ProviderUnavailableError,
    SessionError,
    UnsupportedCapabilityError,
)
from ..contracts import AgentSession, SessionState, new_id


def _map_acp_update(notif: dict[str, Any]) -> dict[str, Any]:
    """ACP session/update notification → bridge-native event dict."""
    upd = (notif.get("params") or {}).get("update") or {}
    kind = upd.get("sessionUpdate") or upd.get("type") or "unknown"
    params: dict[str, Any] = {"native_kind": kind}
    if kind == "agent_message_chunk":
        content = upd.get("content") or {}
        params["text"] = content.get("text", "")
        return {"type": "content_delta", "params": params}
    if kind == "agent_message_end":
        return {"type": "content", "params": params}
    if kind in ("tool_call", "tool_call_update"):
        params["name"] = upd.get("title") or upd.get("kind") or "tool"
        params["status"] = upd.get("status")
        return {"type": "tool_call" if kind == "tool_call" else "tool_result",
                "params": params}
    if kind == "plan":
        params["entries"] = upd.get("entries", [])
        return {"type": "plan_update", "params": params}
    if kind == "available_commands_update":
        params["commands"] = upd.get("availableCommands", [])
        return {"type": "capability_update", "params": params}
    return {"type": "unknown", "params": params, "raw": notif}


class AcpAdapter:
    """ProviderAdapter over a spawned ACP server (`<cli> acp`)."""

    def __init__(self, provider_id: str, cmd: list[str],
                 name: str | None = None, timeout_s: float = 120.0) -> None:
        self.provider_id, self.cmd, self.name = provider_id, cmd, name or provider_id
        self.timeout_s = timeout_s
        self._clients: dict[str, AcpClient] = {}
        self._acp_ids: dict[str, str] = {}   # bridge sid → acp sessionId
        self._sessions: dict[str, AgentSession] = {}

    # -- lifecycle -----------------------------------------------------------

    def _require(self, sid: str) -> AcpClient:
        c = self._clients.get(sid)
        if not c:
            raise SessionError("FAB-SESSION", f"unknown session {sid}",
                               provider=self.provider_id)
        return c

    def detect(self):  # ProviderDescriptor
        from ..registry import REGISTRY
        return next((d for d in REGISTRY.detect_all() if d.id == self.provider_id),
                    None)

    def get_version(self) -> str | None:
        exe = shutil.which(self.cmd[0])
        if not exe:
            return None
        import subprocess
        try:
            out = subprocess.run([exe, "--version"], check=False, capture_output=True,
                                 text=True, timeout=10)
            return (out.stdout or out.stderr).strip().splitlines()[0] or None
        except Exception:  # noqa: BLE001 — version probe is best-effort
            return None

    def get_auth_status(self) -> str:
        # Honest: presence of the binary does not prove auth.
        from ..contracts import AuthState
        return (AuthState.UNVERIFIED
                if shutil.which(self.cmd[0]) else AuthState.UNAUTHENTICATED).value

    def initialize(self) -> None:
        if not shutil.which(self.cmd[0]):
            raise ProviderUnavailableError(
                f"{self.cmd[0]} not on PATH", provider=self.provider_id)

    def create_session(self, **kw: Any) -> AgentSession:
        self.initialize()
        client = AcpClient(self.cmd, timeout_s=self.timeout_s)
        client.start()
        try:
            client.initialize()
            acp_sid = client.new_session(cwd=kw.get("cwd") or ".")
        except Exception:
            client.close()
            raise
        s = AgentSession(id=new_id("ses"), provider=self.provider_id,
                         product_id=kw.get("product_id"),
                         workspace_id=kw.get("workspace_id"),
                         state=SessionState.ACTIVE, resumable=False,
                         provider_session_ref=acp_sid)
        self._clients[s.id] = client
        self._acp_ids[s.id] = acp_sid
        self._sessions[s.id] = s
        return s

    def resume_session(self, session_ref: str) -> AgentSession:
        raise UnsupportedCapabilityError("session-resume",
                                         provider=self.provider_id)

    def list_sessions(self) -> list[AgentSession]:
        return list(self._sessions.values())

    # -- turns ---------------------------------------------------------------

    def send_prompt(self, session_id: str, prompt: str,
                    attachments: list[dict[str, Any]] | None = None) -> None:
        client = self._require(session_id)
        if attachments:
            raise UnsupportedCapabilityError("attachments",
                                             provider=self.provider_id)
        client.prompt(self._acp_ids[session_id], prompt)

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        client = self._require(session_id)
        for notif in client.drain_notifications():
            yield _map_acp_update(notif)

    def respond_to_approval(self, approval_id: str, approved: bool) -> None:
        # ACP permission requests arrive as fs/terminal client methods — not
        # implemented on the stdio client surface; honest unsupported state.
        raise UnsupportedCapabilityError("approvals", provider=self.provider_id)

    def cancel(self, session_id: str) -> None:
        self._require(session_id).cancel(self._acp_ids[session_id])

    def close_session(self, session_id: str) -> None:
        client = self._clients.pop(session_id, None)
        self._acp_ids.pop(session_id, None)
        if session_id in self._sessions:
            self._sessions[session_id].state = SessionState.CLOSED
        if client:
            client.close()

    def dispose(self) -> None:
        for sid in list(self._clients):
            self.close_session(sid)


def devin_adapter() -> AcpAdapter:
    """Devin CLI — native `devin acp` stdio server (verified installed)."""
    return AcpAdapter("devin", ["devin", "acp"], name="Devin CLI")


def claude_acp_adapter() -> AcpAdapter:
    """Claude via ACP when an acp-capable entrypoint exists — caller gates."""
    raise BridgeError("FAB-UNAVAILABLE",
                      "claude ACP entrypoint not detected — use stream-json adapter")
