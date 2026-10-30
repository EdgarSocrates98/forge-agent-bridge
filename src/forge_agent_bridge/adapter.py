"""Provider adapter interface (§5.2) — typed errors, no simulated capability."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable

from .contracts import AgentSession, ProviderDescriptor


class BridgeError(Exception):
    """Typed bridge error — code is part of the contract."""

    def __init__(self, code: str, message: str, *, provider: str | None = None):
        super().__init__(message)
        self.code, self.message, self.provider = code, message, provider


class ProviderUnavailableError(BridgeError):
    def __init__(self, msg: str, provider: str | None = None):
        super().__init__("FAB-UNAVAILABLE", msg, provider=provider)


class UnsupportedCapabilityError(BridgeError):
    def __init__(self, capability: str, provider: str | None = None):
        super().__init__("FAB-UNSUPPORTED",
                         f"capability '{capability}' not supported", provider=provider)


class AuthenticationError(BridgeError):
    def __init__(self, msg: str, provider: str | None = None):
        super().__init__("FAB-AUTH", msg, provider=provider)


class SessionError(BridgeError):
    pass


@runtime_checkable
class ProviderAdapter(Protocol):
    """§5.2 contract — unsupported features raise UnsupportedCapabilityError
    or report unavailable state; never simulated behavior."""

    def detect(self) -> ProviderDescriptor: ...
    def get_version(self) -> str | None: ...
    def get_auth_status(self) -> str: ...
    def initialize(self) -> None: ...
    def create_session(self, **kwargs: Any) -> AgentSession: ...
    def resume_session(self, session_ref: str) -> AgentSession: ...
    def list_sessions(self) -> list[AgentSession]: ...
    def send_prompt(self, session_id: str, prompt: str,
                    attachments: list[dict[str, Any]] | None = None) -> None: ...
    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]: ...
    def respond_to_approval(self, approval_id: str, approved: bool) -> None: ...
    def cancel(self, session_id: str) -> None: ...
    def close_session(self, session_id: str) -> None: ...
    def dispose(self) -> None: ...
