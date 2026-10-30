"""Cycle 28.6 — backup/restore of bridge state.

Backs up: session metadata, event history, context bindings, MCP registry,
budgets, collab, audit. **Never** backs up secrets: pair.token, pairing
device tokens, and any *.secret/keyring files are excluded by construction.
Manifest records what was captured so restore is verifiable.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

# never exported — credentials must not leave the device (§25.8, §28.6)
EXCLUDED = {"pair.token", "pairing.json", "secrets.json", "keyring.json"}
INCLUDED_SUFFIXES = (".json", ".jsonl")


def create_backup(state_dir: Path, out: Path | None = None) -> dict[str, Any]:
    """Tarball of non-secret state under `state_dir` → out (or state_dir/)."""
    out = out or (state_dir / f"backup-{int(time.time())}.tar.gz")
    manifest: dict[str, Any] = {"created_at": time.time(),
                                "files": [], "excluded": []}
    with tempfile.TemporaryDirectory() as td, \
            tarfile.open(out, "w:gz") as tar:
        for f in sorted(state_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(state_dir)
            if f.name in EXCLUDED or any(
                    p.name in EXCLUDED for p in rel.parents):
                manifest["excluded"].append(str(rel))
                continue
            if f.suffix not in INCLUDED_SUFFIXES:
                manifest["excluded"].append(str(rel))
                continue
            tar.add(f, arcname=str(rel))
            manifest["files"].append(
                {"path": str(rel), "bytes": f.stat().st_size})
        mf = Path(td) / "manifest.json"
        mf.write_text(json.dumps(manifest, indent=1))
        tar.add(mf, arcname="manifest.json")
    manifest["out"] = str(out)
    return manifest


def restore_backup(backup: Path, state_dir: Path) -> dict[str, Any]:
    """Extract a backup into `state_dir`. Refuses secret paths — a backup
    must never inject credentials (they are re-paired, not restored)."""
    restored, refused = [], []
    with tarfile.open(backup) as tar:
        for m in tar.getmembers():
            name = Path(m.name).name
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                refused.append(m.name)              # traversal guard
                continue
            if name in EXCLUDED:
                refused.append(m.name)              # no secrets restore
                continue
            if m.isfile():
                tar.extract(m, state_dir, filter="data")
                restored.append(m.name)
    return {"restored": restored, "refused": refused}
