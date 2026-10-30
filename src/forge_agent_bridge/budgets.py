"""Budget ledger (§23.4) — limits per scope/window over real usage.

Records token usage from usage.updated events; checks limits BEFORE a
prompt is accepted. Provider-reported tokens are real data; when a
provider reports nothing the entry is flagged estimated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapter import BridgeError
from .contracts import utcnow
from .local_bridge import state_dir


def _day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


class BudgetLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "budget.json")

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"limits": {}, "usage": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1))
        self.path.chmod(0o600)

    # -- limits --------------------------------------------------------------

    def set_limit(self, scope: str, key: str, window: str,
                  tokens: int) -> dict[str, Any]:
        """scope: user|workspace|product|provider|session · window: day|month."""
        if window not in ("day", "month"):
            raise BridgeError("FAB-VALIDATION", "window must be day|month")
        data = self._load()
        data["limits"][f"{scope}:{key}:{window}"] = tokens
        self._save(data)
        return {"scope": scope, "key": key, "window": window, "tokens": tokens}

    def limits(self) -> dict[str, Any]:
        return dict(self._load()["limits"])

    # -- usage ---------------------------------------------------------------

    def record(self, scope_map: dict[str, str], tokens_in: int,
               tokens_out: int, *, estimated: bool = False) -> None:
        """scope_map: {user:.., workspace:.., product:.., provider:.., session:..}."""
        data = self._load()
        for scope, key in scope_map.items():
            if not key:
                continue
            for window, wkey in (("day", _day()), ("month", _month())):
                k = f"{scope}:{key}:{window}:{wkey}"
                u = data["usage"].setdefault(
                    k, {"in": 0, "out": 0, "estimated": estimated, "n": 0})
                u["in"] += tokens_in
                u["out"] += tokens_out
                u["n"] += 1
                u["estimated"] = u["estimated"] or estimated
                u["updated_at"] = utcnow()
        self._save(data)

    def check(self, scope_map: dict[str, str]) -> None:
        """Raise FAB-BUDGET when any configured limit is already exceeded."""
        data = self._load()
        for scope, key in scope_map.items():
            if not key:
                continue
            for window, wkey in (("day", _day()), ("month", _month())):
                lim = data["limits"].get(f"{scope}:{key}:{window}")
                if lim is None:
                    continue
                u = data["usage"].get(f"{scope}:{key}:{window}:{wkey}")
                used = (u["in"] + u["out"]) if u else 0
                if used >= lim:
                    raise BridgeError(
                        "FAB-BUDGET",
                        f"{scope}:{key} {window} budget {lim} tokens exhausted")

    def summary(self) -> dict[str, Any]:
        return self._load()
