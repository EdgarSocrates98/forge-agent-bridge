"""Provider registry (§19.3) — detection, capabilities, health, selection."""

from __future__ import annotations

import shutil
from typing import Any

from .adapter import ProviderAdapter
from .contracts import AuthState, CapabilityState, ProviderCapability, ProviderDescriptor

# Versioned capability vocabulary (§26.1) — every provider declares the
# SAME capability names so the matrix is comparable row-by-row.
CAPABILITY_VOCAB: tuple[str, ...] = (
    "chat", "streaming", "session-resume", "cancel", "tool-calling",
    "mcp", "files", "approvals", "images", "models", "subagents",
    "plans", "usage", "cloud-handoff",
)
MATRIX_VERSION = "forge/ProviderCapabilityMatrix/1"


def _caps(**kw: str) -> list[tuple[str, CapabilityState]]:
    """Build a full-vocabulary capability list; omitted → UNSUPPORTED."""
    out: list[tuple[str, CapabilityState]] = []
    for name in CAPABILITY_VOCAB:
        key = name.replace("-", "_")
        state = getattr(CapabilityState, kw.get(key, "UNSUPPORTED"))
        out.append((name, state))
    return out


# Declarative detection catalog — no auto-discovery of arbitrary binaries;
# these are the three sanctioned providers plus the test double.
# States are honest: verified mechanisms are SUPPORTED, mechanisms confirmed
# to exist on the CLI but not yet homologated live are UNVERIFIED, and
# anything absent or undetermined is UNSUPPORTED — never fabricated.
CATALOG: dict[str, dict[str, Any]] = {
    "claude-code": {
        "name": "Claude Code",
        "executable": "claude",
        "kind": "cli-acp",
        # mechanism: `claude -p --output-format stream-json
        # --input-format stream-json` (verified on installed CLI)
        "capabilities": _caps(
            chat="SUPPORTED", streaming="SUPPORTED",
            session_resume="UNVERIFIED", cancel="SUPPORTED",
            tool_calling="SUPPORTED", mcp="SUPPORTED",
            files="SUPPORTED", approvals="SUPPORTED",
            images="UNVERIFIED", models="SUPPORTED",
            subagents="UNVERIFIED", plans="UNVERIFIED",
            usage="UNVERIFIED", cloud_handoff="UNSUPPORTED"),
    },
    "codex": {
        "name": "Codex CLI",
        "executable": "codex",
        "kind": "cli-jsonl",
        # mechanism: `codex exec --json` + `codex exec resume` (verified)
        "capabilities": _caps(
            chat="SUPPORTED", streaming="SUPPORTED",
            session_resume="UNVERIFIED", cancel="SUPPORTED",
            tool_calling="UNVERIFIED", mcp="UNVERIFIED",
            files="UNVERIFIED", approvals="UNVERIFIED",
            images="UNSUPPORTED", models="SUPPORTED",
            subagents="UNSUPPORTED", plans="UNVERIFIED",
            usage="UNVERIFIED", cloud_handoff="UNSUPPORTED"),
    },
    "devin": {
        "name": "Devin CLI",
        "executable": "devin",
        "kind": "cli-acp",
        # mechanism: `devin acp` (ACP/JSON-RPC, verified live 2026-10-30 —
        # transcript docs/audits/evidence/devin_acp_20261030T093504.jsonl)
        "capabilities": _caps(
            chat="SUPPORTED", streaming="SUPPORTED",
            session_resume="SUPPORTED", cancel="UNVERIFIED",
            tool_calling="UNVERIFIED", mcp="UNVERIFIED",
            files="UNVERIFIED", approvals="UNVERIFIED",
            images="UNSUPPORTED", models="UNVERIFIED",
            subagents="UNVERIFIED", plans="UNVERIFIED",
            usage="SUPPORTED", cloud_handoff="UNVERIFIED"),
    },
    "fake": {
        "name": "Fake Provider (tests)",
        "executable": None,
        "kind": "fake",
        "capabilities": _caps(
            chat="SUPPORTED", streaming="SUPPORTED",
            session_resume="SUPPORTED", cancel="SUPPORTED",
            tool_calling="SUPPORTED", mcp="SUPPORTED",
            files="SUPPORTED", approvals="SUPPORTED",
            images="SUPPORTED", models="SUPPORTED",
            subagents="SUPPORTED", plans="SUPPORTED",
            usage="SUPPORTED", cloud_handoff="UNSUPPORTED"),
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
                matrix_version=MATRIX_VERSION,
            ))
        return out

    def available(self) -> list[str]:
        return [d.id for d in self.detect_all() if d.executable or d.kind == "fake"]


REGISTRY = ProviderRegistry()
