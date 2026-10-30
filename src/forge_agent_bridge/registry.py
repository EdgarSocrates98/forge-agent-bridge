"""Provider registry (§19.3) — detection, capabilities, health, selection."""

from __future__ import annotations

import shutil
from typing import Any

from .adapter import ProviderAdapter
from .contracts import AuthState, CapabilityState, ProviderCapability, ProviderDescriptor

# Declarative detection catalog — no auto-discovery of arbitrary binaries;
# these are the three sanctioned providers plus the test double.
CATALOG: dict[str, dict[str, Any]] = {
    "claude-code": {
        "name": "Claude Code",
        "executable": "claude",
        "kind": "cli-acp",
        "capabilities": [
            ("streaming", CapabilityState.SUPPORTED),
            ("session-resume", CapabilityState.UNVERIFIED),
            ("tool-calling", CapabilityState.SUPPORTED),
            ("mcp", CapabilityState.SUPPORTED),
            ("approvals", CapabilityState.SUPPORTED),
            ("usage", CapabilityState.UNVERIFIED),
        ],
    },
    "codex": {
        "name": "Codex CLI",
        "executable": "codex",
        "kind": "cli-jsonl",
        "capabilities": [
            ("streaming", CapabilityState.UNVERIFIED),
            ("session-resume", CapabilityState.UNVERIFIED),
            ("tool-calling", CapabilityState.UNVERIFIED),
            ("approvals", CapabilityState.UNVERIFIED),
            ("sandbox", CapabilityState.REQUIRES_CONFIG),
        ],
    },
    "devin": {
        "name": "Devin CLI",
        "executable": "devin",
        "kind": "cli-jsonl",
        "capabilities": [
            ("streaming", CapabilityState.UNVERIFIED),
            ("session-resume", CapabilityState.UNVERIFIED),
            ("cloud-handoff", CapabilityState.UNVERIFIED),
            ("usage", CapabilityState.UNVERIFIED),
        ],
    },
    "fake": {
        "name": "Fake Provider (tests)",
        "executable": None,
        "kind": "fake",
        "capabilities": [(c, CapabilityState.SUPPORTED) for c in (
            "streaming", "session-resume", "tool-calling", "approvals", "usage")],
    },
}


class ProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, provider_id: str, adapter: ProviderAdapter) -> None:
        self._adapters[provider_id] = adapter

    def adapter(self, provider_id: str) -> ProviderAdapter | None:
        """Explicit registration wins; otherwise lazily resolve a real
        adapter for the provider kind. Missing binary → None (caller
        raises FAB-UNAVAILABLE)."""
        if provider_id in self._adapters:
            return self._adapters[provider_id]
        adapter = self._resolve(provider_id)
        if adapter:
            self._adapters[provider_id] = adapter
        return adapter

    @staticmethod
    def _resolve(provider_id: str) -> ProviderAdapter | None:
        meta = CATALOG.get(provider_id)
        if not meta:
            return None
        exe = meta.get("executable")
        if exe and not shutil.which(exe):
            return None
        if provider_id == "devin":
            from .providers.acp_adapter import devin_adapter
            return devin_adapter()
        if provider_id == "claude-code":
            from .providers.claude import claude_adapter
            return claude_adapter()
        if provider_id == "codex":
            from .providers.codex import codex_adapter
            return codex_adapter()
        if provider_id == "fake":
            from .providers.fake import FakeAdapter
            return FakeAdapter()
        return None

    def detect_all(self) -> list[ProviderDescriptor]:
        """Installed-CLI detection via PATH — honest `unverified` auth."""
        out: list[ProviderDescriptor] = []
        for pid, meta in CATALOG.items():
            exe = meta["executable"]
            installed = shutil.which(exe) if exe else None
            out.append(ProviderDescriptor(
                id=pid, name=meta["name"], kind=meta["kind"],
                executable=installed,
                capabilities=[ProviderCapability(name=n, state=s)
                              for n, s in meta["capabilities"]],
                auth_state=(AuthState.UNVERIFIED if installed
                            else AuthState.UNAUTHENTICATED),
            ))
        return out

    def available(self) -> list[str]:
        return [d.id for d in self.detect_all() if d.executable or d.kind == "fake"]


REGISTRY = ProviderRegistry()
