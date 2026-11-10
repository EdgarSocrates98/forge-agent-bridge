"""Obsidian projections must cross the same re-authorization boundary as any source."""

import pytest

from forge_agent_bridge.adapter import BridgeError
from forge_agent_bridge.context import ContextStore, KnowledgeContextPack, ProductAgentSessionContext


def _pack(source: str) -> KnowledgeContextPack:
    return KnowledgeContextPack(
        pack_id="obsidian-pack",
        workspace_id="ws-1",
        product_id="p1",
        principal="agent-1",
        source_versions={source: "sha256:note"},
        selected_items=["note-1"],
        items=[
            {
                "item_id": "note-1",
                "source_id": source,
                "document_id": "runbooks/spark.md",
                "workspace_id": "ws-1",
                "product_id": "p1",
                "version": "sha256:note",
            }
        ],
    )


def test_obsidian_source_requires_explicit_allowlist_and_reauthorization(tmp_path) -> None:
    source = "obsidian:vault-1:runbooks/spark.md"
    store = ContextStore(path=tmp_path)
    store.bind(
        "s9",
        ProductAgentSessionContext(
            identity="agent-1",
            workspace_id="ws-1",
            product_id="p1",
            allowed_knowledge_sources=[source],
        ),
    )
    assert store.authorize_knowledge_pack("s9", _pack(source)).pack_id == "obsidian-pack"

    store.bind(
        "s9",
        ProductAgentSessionContext(
            identity="agent-1",
            workspace_id="ws-1",
            product_id="p1",
            allowed_knowledge_sources=["obsidian:vault-1:other.md"],
        ),
    )
    with pytest.raises(BridgeError, match="allowlist"):
        store.authorize_knowledge_pack("s9", _pack(source))
