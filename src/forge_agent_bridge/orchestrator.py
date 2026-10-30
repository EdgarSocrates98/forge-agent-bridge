"""Session orchestrator — the Bridge service surface the Portal consumes.

Composes adapter + normalization + event buffer into one API:
create session → prompt → drain events → replay → cancel → close.
All state is in-memory per bridge process (durable persistence is a
remote-runner concern, Cycle 23).
"""

from __future__ import annotations

from typing import Any

from .adapter import BridgeError, ProviderAdapter
from .contracts import AgentSession
from .events import EventBuffer, normalize


class BridgeOrchestrator:
    def __init__(self, adapter: ProviderAdapter, provider_id: str) -> None:
        self.adapter, self.provider_id = adapter, provider_id
        self.sessions: dict[str, AgentSession] = {}
        self.buffers: dict[str, EventBuffer] = {}

    def create_session(self, **kw: Any) -> AgentSession:
        s = self.adapter.create_session(**kw)
        self.sessions[s.id] = s
        self.buffers[s.id] = EventBuffer(s.id)
        self._push(s.id, {"type": "session/new", "params": {"session_id": s.id}})
        return s

    def prompt(self, session_id: str, text: str) -> None:
        self._require(session_id)
        self._push(session_id, {"type": "prompt", "params": {"text": text}})
        self.adapter.send_prompt(session_id, text)

    def drain(self, session_id: str) -> int:
        """Pull native events → normalize → buffer. Returns count stored."""
        self._require(session_id)
        n = 0
        for native in self.adapter.stream_events(session_id):
            if self._push(session_id, native):
                n += 1
        return n

    def replay(self, session_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        self._require(session_id)
        return self.buffers[session_id].replay(after_seq)

    def cancel(self, session_id: str) -> None:
        self.adapter.cancel(session_id)
        self._push(session_id, {"type": "session/cancel",
                                "params": {"session_id": session_id}})

    def close(self, session_id: str) -> None:
        self.adapter.close_session(session_id)
        self._push(session_id, {"type": "session/close",
                                "params": {"session_id": session_id}})

    def _push(self, session_id: str, native: dict[str, Any]) -> bool:
        return self.buffers[session_id].push(
            normalize(native, self.provider_id, session_id))

    def _require(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise BridgeError("FAB-SESSION", f"unknown session {session_id}")


def build_orchestrator(provider_id: str) -> BridgeOrchestrator:
    """Resolve an adapter for the provider. `fake` works anywhere;
    real providers resolve via registry-installed adapters."""
    from .registry import REGISTRY
    if provider_id == "fake":
        from .providers.fake import FakeAdapter
        return BridgeOrchestrator(FakeAdapter(), provider_id)
    adapter = REGISTRY.adapter(provider_id)
    if not adapter:
        raise BridgeError("FAB-UNAVAILABLE",
                          f"no adapter registered for '{provider_id}' — "
                          "install/configure the provider first")
    return BridgeOrchestrator(adapter, provider_id)
