"""Forge Agent Bridge → Obsidian session handoff projection.

Composes a sanitized ``theforge/ObsidianNoteRef/v1`` note summarizing an
agent session or context-pack handoff (allowed sources only — bodies stay
in the bridge state, never in the note).  Projection only — the vendored
``forge_agent_bridge._forge_obsidian`` engine owns vault bytes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from forge_agent_bridge._forge_obsidian.notes import build_note_ref, section_yaml

FORGE_ID = "forge-agent-bridge"


def build_obsidian_session_handoff(
    *,
    title: str,
    summary: str,
    workspace: str,
    vault_id: str,
    session: Mapping[str, Any] | None = None,
    context_packs: Iterable[Mapping[str, Any]] | None = None,
    allowed_sources: Iterable[str] | None = None,
    related_refs: Iterable[str] | None = None,
    note_path: str | None = None,
    confidence: str = "unknown",
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a session handoff note (session + packs + allowed sources)."""
    return build_note_ref(
        forge_id=FORGE_ID,
        title=title,
        summary=summary,
        workspace=workspace,
        vault_id=vault_id,
        kind="session-handoff",
        body_sections=[
            section_yaml("Session", dict(session or {})),
            section_yaml("Context packs", list(context_packs or [])),
            section_yaml("Allowed sources", list(allowed_sources or [])),
        ],
        note_path=note_path,
        confidence=confidence,
        tags=["agent", "bridge", "handoff"],
        related=list(related_refs or []),
        provenance=provenance,
    )


__all__ = ["FORGE_ID", "build_obsidian_session_handoff"]
