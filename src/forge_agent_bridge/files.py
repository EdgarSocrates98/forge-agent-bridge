"""Workspace file service (§22.3) — preview/download/upload/history/restore.

Path safety: every request resolves inside the declared workspace root —
traversal outside it is FAB-FORBIDDEN. Writes require `approved=true`
in the request (Portal mutation gate); every write snapshots the prior
version under ~/.forge-bridge/versions/.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .adapter import BridgeError
from .contracts import utcnow
from .local_bridge import state_dir

MAX_PREVIEW = 256 * 1024  # 256 KiB preview cap — honest partial flag beyond
TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".sql", ".py",
            ".ts", ".js", ".html", ".css", ".diff", ".patch", ".toml", ".xml",
            ".log", ".sh"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls"}


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        return {"json": "json", "yaml": "yaml", "yml": "yaml",
                "csv": "csv", "sql": "sql", "py": "python",
                "html": "html", "css": "css",
                "diff": "diff", "patch": "diff"}.get(ext.lstrip("."), "text")
    if ext in IMG_EXT:
        return "image"
    if ext in DOC_EXT:
        return "binary"
    return "text" if ext in TEXT_EXT else "binary"


class FileService:
    """File ops rooted at a workspace directory (allowlist enforcement)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel.lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise BridgeError("FAB-FORBIDDEN",
                              f"path escapes workspace root: {rel}")
        return p

    def list_dir(self, rel: str = ".") -> list[dict[str, Any]]:
        d = self._resolve(rel)
        if not d.is_dir():
            raise BridgeError("FAB-NOT-FOUND", f"not a directory: {rel}")
        out = []
        for e in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if e.name.startswith(".forge"):
                continue
            out.append({"name": e.name, "dir": e.is_dir(),
                        "size": e.stat().st_size if e.is_file() else None,
                        "kind": kind_of(e) if e.is_file() else "dir"})
        return out

    def preview(self, rel: str) -> dict[str, Any]:
        p = self._resolve(rel)
        if not p.is_file():
            raise BridgeError("FAB-NOT-FOUND", f"not a file: {rel}")
        size = p.stat().st_size
        kind = kind_of(p)
        if kind in ("binary", "image"):
            return {"path": rel, "kind": kind, "size": size,
                    "preview": None,
                    "note": "binary preview not rendered — download only"}
        data = p.read_bytes()[:MAX_PREVIEW]
        return {"path": rel, "kind": kind, "size": size,
                "preview": data.decode("utf-8", errors="replace"),
                "truncated": size > MAX_PREVIEW}

    def read_bytes(self, rel: str) -> bytes:
        p = self._resolve(rel)
        if not p.is_file():
            raise BridgeError("FAB-NOT-FOUND", f"not a file: {rel}")
        return p.read_bytes()

    def upload(self, rel: str, data: bytes, *, approved: bool) -> dict[str, Any]:
        if not approved:
            raise BridgeError("FAB-APPROVAL-REQUIRED",
                              "file write requires approved=true")
        p = self._resolve(rel)
        if p.exists():
            self._snapshot(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return {"path": rel, "size": len(data), "saved": True}

    def _snapshot(self, p: Path) -> Path:
        rel = p.relative_to(self.root)
        digest = hashlib.sha256(str(rel).encode()).hexdigest()[:16]
        vd = state_dir() / "versions" / digest
        vd.mkdir(parents=True, exist_ok=True)
        dest = vd / f"{utcnow().replace(':', '-')}_{p.name}"
        shutil.copy2(p, dest)
        return dest

    def history(self, rel: str) -> list[dict[str, Any]]:
        digest = hashlib.sha256(str(rel).encode()).hexdigest()[:16]
        vd = state_dir() / "versions" / digest
        if not vd.is_dir():
            return []
        return [{"version": e.name, "size": e.stat().st_size}
                for e in sorted(vd.iterdir(), reverse=True)]

    def restore(self, rel: str, version: str, *, approved: bool) -> dict[str, Any]:
        if not approved:
            raise BridgeError("FAB-APPROVAL-REQUIRED",
                              "restore requires approved=true")
        digest = hashlib.sha256(str(rel).encode()).hexdigest()[:16]
        src = (state_dir() / "versions" / digest / version).resolve()
        vd = (state_dir() / "versions" / digest).resolve()
        if vd not in src.parents or not src.is_file():
            raise BridgeError("FAB-NOT-FOUND", f"unknown version {version}")
        dst = self._resolve(rel)
        if dst.exists():
            self._snapshot(dst)
        shutil.copy2(src, dst)
        return {"path": rel, "restored": version}
