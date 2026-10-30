"""Session metadata store (§20.3) — durable per-session annotations.

Lives beside pair.token at ~/.forge-bridge/sessions.json. Holds the
Portal-editable fields that outlive an in-memory orchestrator: title,
product association, favorite/archive flags, visibility, notes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import utcnow
from .local_bridge import state_dir

FIELDS = {"title", "product_id", "workspace_id", "favorite", "archived",
          "visibility", "notes", "provider"}


class SessionMetaStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "sessions.json")

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1))
        self.path.chmod(0o600)

    def get(self, session_id: str) -> dict[str, Any]:
        return dict(self._load().get(session_id) or {})

    def list(self, *, include_archived: bool = False) -> dict[str, Any]:
        data = self._load()
        if not include_archived:
            data = {k: v for k, v in data.items() if not v.get("archived")}
        return data

    def upsert(self, session_id: str, **fields: Any) -> dict[str, Any]:
        data = self._load()
        meta = dict(data.get(session_id) or {})
        meta.setdefault("created_at", utcnow())
        for k, v in fields.items():
            if k in FIELDS:
                meta[k] = v
        meta["updated_at"] = utcnow()
        data[session_id] = meta
        self._save(data)
        return dict(meta)

    def delete(self, session_id: str) -> bool:
        data = self._load()
        if session_id not in data:
            return False
        del data[session_id]
        self._save(data)
        return True
