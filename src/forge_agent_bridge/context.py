"""Cycle 27 — Product Context binding, MCP federation, knowledge capture.

Contracts:
- forge/ProductAgentSessionContext/v1 — what a session is allowed to see/do.
- forge/MCPServerDescriptor/v1   — federated MCP registry entries.
- forge/AgentContextDelta/v1     — reviewed knowledge captured from a session.

Provenance is recorded at bind time so an old execution can be answered with
"which context version did it run against" (§27.4).
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .adapter import BridgeError

CONTEXT_SCHEMA = "forge/ProductAgentSessionContext/v1"
DELTA_SCHEMA = "forge/AgentContextDelta/v1"
MCP_SCHEMA = "forge/MCPServerDescriptor/v1"


class ProductAgentSessionContext(BaseModel):
    """forge/ProductAgentSessionContext/v1 — session context binding."""

    schema_: str = Field(default=CONTEXT_SCHEMA, alias="schema")
    identity: str = ""                       # principal bound at create
    workspace_id: str | None = None
    product_id: str | None = None
    provider: str = ""
    agent_profile: str = "default"
    allowed_knowledge_sources: list[str] = Field(default_factory=list)
    allowed_datasets: list[str] = Field(default_factory=list)
    allowed_metrics: list[str] = Field(default_factory=list)
    allowed_apis: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    mcp_registry: list[str] = Field(default_factory=list)  # server ids
    permissions: list[str] = Field(default_factory=list)
    budget_usd: float | None = None
    context_version: int = 1
    policy_version: str = "forge/PolicyBundle/1"
    expires_at: float | None = None

    model_config = {"populate_by_name": True}


class AgentContextDelta(BaseModel):
    """forge/AgentContextDelta/v1 — reviewed knowledge captured from a run."""

    schema_: str = Field(default=DELTA_SCHEMA, alias="schema")
    session_id: str
    product_id: str
    source_event_ids: list[str] = Field(default_factory=list)
    statement: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    review: str = "draft"                    # draft|reviewed|approved|rejected
    reviewer: str = ""
    created_at: str = ""

    model_config = {"populate_by_name": True}


class MCPServerDescriptor(BaseModel):
    """forge/MCPServerDescriptor/v1 — federated MCP registry entry."""

    schema_: str = Field(default=MCP_SCHEMA, alias="schema")
    server_id: str
    name: str
    endpoint: str = "stdio"                  # stdio | http | local-lib
    trust: str = "unverified"                # verified|unverified|revoked
    capabilities: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    health: str = "unverified"               # verified|unverified|error

    model_config = {"populate_by_name": True}


class ContextStore:
    """Durable binding of session → context + delta outbox (JSONL, 0600)."""

    def __init__(self, path: Path | None = None) -> None:
        from .local_bridge import state_dir
        self._ctx = (path or state_dir()) / "session_contexts.json"
        self._delta = (path or state_dir()) / "context_deltas.jsonl"
        self._data: dict[str, Any] = {}
        if self._ctx.exists():
            with contextlib.suppress(Exception):
                self._data = json.loads(self._ctx.read_text())

    def bind(self, session_id: str, ctx: ProductAgentSessionContext) -> None:
        self._data[session_id] = ctx.model_dump(mode="json", by_alias=True)
        self._ctx.write_text(json.dumps(self._data, indent=1))

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._data.get(session_id)

    def context_of(self, session_id: str) -> ProductAgentSessionContext | None:
        d = self._data.get(session_id)
        return ProductAgentSessionContext.model_validate(d) if d else None

    def assert_allowed(self, session_id: str, *, tool: str | None = None,
                       source: str | None = None,
                       dataset: str | None = None) -> None:
        """§27.6 — tool authorization against the bound context."""
        ctx = self.context_of(session_id)
        if ctx is None:
            return                       # unbound session: broker decides
        if ctx.expires_at and time.time() > ctx.expires_at:
            raise BridgeError("FAB-FORBIDDEN", "session context expired")
        def _deny(what: str, val: str, allowed: list[str]) -> None:
            if allowed and val not in allowed:
                raise BridgeError(
                    "FAB-FORBIDDEN",
                    f"{what} '{val}' not in session context allowlist")
        if tool:
            _deny("tool", tool, ctx.allowed_tools)
        if source:
            _deny("knowledge source", source, ctx.allowed_knowledge_sources)
        if dataset:
            _deny("dataset", dataset, ctx.allowed_datasets)

    def record_delta(self, delta: AgentContextDelta) -> None:
        """§27.7 — knowledge capture outbox; PF indexes after review."""
        with self._delta.open("a") as f:
            f.write(json.dumps(delta.model_dump(mode="json",
                                                by_alias=True)) + "\n")

    def deltas(self, product_id: str | None = None,
               review: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self._delta.exists():
            return out
        for line in self._delta.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if product_id and d.get("product_id") != product_id:
                continue
            if review and d.get("review") != review:
                continue
            out.append(d)
        return out


class MCPFederation:
    """§27.5 — federated MCP server registry with trust states."""

    def __init__(self, path: Path | None = None) -> None:
        from .local_bridge import state_dir
        self._file = (path or state_dir()) / "mcp_registry.json"
        self._data: dict[str, Any] = {}
        if self._file.exists():
            with contextlib.suppress(Exception):
                self._data = json.loads(self._file.read_text())
        if not self._data:
            # seed with the known local federation — all unverified until
            # a real handshake/health check proves otherwise
            for sid, name in (
                ("product-forge", "Product Forge MCP"),
                ("sparkforge-aws", "SparkForge AWS"),
                ("forge-lens", "Forge Lens"),
                ("data-sentinel", "Data Sentinel"),
            ):
                self._data[sid] = MCPServerDescriptor(
                    server_id=sid, name=name).model_dump(mode="json",
                                                         by_alias=True)
            self._save()

    def _save(self) -> None:
        self._file.write_text(json.dumps(self._data, indent=1))

    def register(self, d: MCPServerDescriptor) -> dict[str, Any]:
        self._data[d.server_id] = d.model_dump(mode="json", by_alias=True)
        self._save()
        return self._data[d.server_id]

    def list(self) -> list[dict[str, Any]]:
        return list(self._data.values())

    def get(self, server_id: str) -> dict[str, Any] | None:
        return self._data.get(server_id)

    def set_health(self, server_id: str, health: str) -> dict[str, Any]:
        if server_id not in self._data:
            raise BridgeError("FAB-NOT-FOUND", f"mcp server {server_id}")
        self._data[server_id]["health"] = health
        self._save()
        return self._data[server_id]

    def allowed_for(self, ctx: ProductAgentSessionContext,
                    server_id: str) -> bool:
        """Access conditioned on context allowlist + live trust (§27.5)."""
        d = self._data.get(server_id)
        if d is None or d["trust"] == "revoked":
            return False
        return not (ctx.mcp_registry and server_id not in ctx.mcp_registry)
