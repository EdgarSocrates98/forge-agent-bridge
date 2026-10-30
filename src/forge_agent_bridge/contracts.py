"""Typed, versioned bridge contracts (§5.1–5.3)."""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return f"{prefix}_{''.join(secrets.choice(alphabet) for _ in range(12))}"


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    EXPERIMENTAL = "experimental"
    REQUIRES_CONFIG = "requires-configuration"
    REQUIRES_AUTH = "requires-authentication"
    UNVERIFIED = "unverified"


class AuthState(StrEnum):
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    EXPIRED = "expired"
    UNVERIFIED = "unverified"


class SessionState(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    FAILED = "failed"


class ProviderCapability(BaseModel):
    name: str
    state: CapabilityState = CapabilityState.UNVERIFIED
    detail: str = ""


class ProviderDescriptor(BaseModel):
    id: str
    name: str
    kind: Literal["cli-acp", "cli-jsonl", "remote-api", "fake"] = "cli-acp"
    executable: str | None = None
    version: str | None = None
    capabilities: list[ProviderCapability] = Field(default_factory=list)
    auth_state: AuthState = AuthState.UNVERIFIED


class AgentSession(BaseModel):
    id: str
    provider: str
    product_id: str | None = None
    workspace_id: str | None = None
    state: SessionState = SessionState.CREATED
    provider_session_ref: str | None = None
    title: str = ""
    created_at: str = Field(default_factory=utcnow)
    resumable: bool = False


class AgentTurn(BaseModel):
    id: str
    session_id: str
    index: int = 0
    state: Literal["started", "completed", "failed", "cancelled"] = "started"
    prompt: str = ""


class AgentApproval(BaseModel):
    id: str
    session_id: str
    turn_id: str | None = None
    kind: str = "command"
    detail: str = ""
    state: Literal["requested", "approved", "denied", "expired"] = "requested"


class AgentUsage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


EVENT_TYPES = {
    "session.created", "session.resumed", "session.closed",
    "turn.started", "turn.completed", "turn.failed",
    "message.delta", "message.completed",
    "tool.started", "tool.progress", "tool.completed",
    "approval.requested", "approval.resolved",
    "artifact.created", "artifact.updated",
    "plan.updated", "usage.updated",
    "runtime.error", "connection.disconnected",
}
