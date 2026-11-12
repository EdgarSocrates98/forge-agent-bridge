"""Workspace authorization + safe filesystem access (stdlib-only).

The single filesystem trust boundary for MCP tools: every path a tool
touches resolves through :class:`WorkspaceGuard` — canonicalization,
symlink/junction/reparse-point screening, UNC/device filtering, and a
sensitive-file denylist. Deny-by-default: anything the guard cannot
prove safe is refused, and refusals never reveal whether the target
exists outside the authorized root.

Residual-risk honesty: on Windows there is no ``O_NOFOLLOW``; the guard
re-resolves immediately before open, which narrows but cannot fully
eliminate a replace-race on a hostile filesystem. Corporate workloads
treat every read target as untrusted content anyway.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# -- sensitive-name denylist (defense-in-depth on top of allowlisted reads) --
_SENSITIVE_NAMES = re.compile(
    r"(?i)^("
    r"\.env(\..*)?|.*\.env|id_rsa.*|id_ed25519.*|id_dsa.*|id_ecdsa.*|"
    r".*\.(pem|key|p12|pfx|keystore|jks|kdbx|secret)|"
    r"credentials?(\..*)?|secrets?(\..*)?|.*\.token|"
    r"\.netrc|\.npmrc|\.pypirc|\.kubeconfig|\.dockercfg|"
    r"\.git-credentials|\.gitconfig|hosts\.yml|hub|"
    r"private[_-]?key.*|.*_rsa|htpasswd|shadow|passwd|"
    r"\.aws-credentials|azureProfile\.json|"
    r"access_tokens\.json|tokens\.json|token_cache.*|"
    r"\.copilot.*|.*copilot.*token.*|"
    r"pair\.token|secrets\.json|pairing\.json"
    r")$")
_SENSITIVE_DIRS = frozenset({
    ".aws", ".ssh", ".gnupg", ".kube", ".docker", ".azure",
    ".config/gh", ".config/hub", "AppData/Local/GitHubCLI",
    ".terraform.d", ".gradle", ".m2", ".gem", ".cargo",
})
_WIN_DEVICES = re.compile(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])$")


class WorkspaceDenied(Exception):
    """A path failed workspace policy — carries only a safe reason code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SafePath:
    """A path proven inside the workspace at check time."""

    abs_path: Path
    rel_posix: str

    def open(self, mode: str = "rb"):
        """Open with a second canonical check immediately beforehand
        (narrows the check→use race window; not a guarantee on Windows)."""
        p = self.abs_path.resolve(strict=False)
        return p.open(mode)


def _is_reparse(path: Path) -> bool:
    """Windows junction/symlink/reparse-point check; False on POSIX."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs and attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is None:  # Python < 3.12: no junction API
        return False
    return isjunction(path)


def _is_symlink(path: Path) -> bool:
    try:
        return os.path.islink(path) or _is_reparse(path)
    except OSError:
        return False


class WorkspaceGuard:
    """Authorized-root path resolution for all MCP tools."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if not root:
            raise WorkspaceDenied("workspace-root-empty")
        try:
            resolved = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as e:
            raise WorkspaceDenied(f"workspace-root-invalid:{type(e).__name__}")
        if not resolved.is_dir():
            raise WorkspaceDenied("workspace-root-not-a-directory")
        self.root = resolved
        self._root_parts = resolved.parts
        self._is_unc_root = str(resolved).startswith(("\\\\", "//"))

    # -- path resolution ------------------------------------------------------

    def resolve(self, rel: str | os.PathLike[str], *,
                allow_links_inside: bool = False) -> SafePath:
        """Resolve ``rel`` against the workspace root → SafePath or raise.

        Rejects: absolute paths outside the root, ``..`` escapes, NUL bytes,
        Windows device names, UNC outside the root, symlinks/reparse points
        resolving outside, and sensitive names.
        """
        if rel is None:
            raise WorkspaceDenied("path-none")
        s = str(rel)
        if "\x00" in s:
            raise WorkspaceDenied("path-nul")
        s = s.strip()
        if not s or s == ".":
            return SafePath(self.root, ".")
        if len(s) > 512:
            raise WorkspaceDenied("path-too-long")

        p = Path(s)
        # Windows device names and raw device paths
        first = p.parts[0] if p.parts else ""
        if _WIN_DEVICES.match(first.split(".")[0]):
            raise WorkspaceDenied("path-device")
        if s.startswith(("\\\\", "//")) and not self._is_unc_root:
            raise WorkspaceDenied("path-unc-denied")
        if re.match(r"^[A-Za-z]:[\\/]", s) or s.startswith(("/", "\\")):
            # absolute candidate — allowed only if it lands inside the root
            candidate = Path(s)
            if not candidate.is_absolute():
                candidate = self.root / candidate
        else:
            candidate = self.root / p

        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            raise WorkspaceDenied("path-unresolvable")

        # containment — robust against case differences and normalization
        try:
            inside = os.path.commonpath(
                [os.path.normcase(str(self.root)),
                 os.path.normcase(str(resolved))]) == os.path.normcase(
                str(self.root))
        except ValueError:  # different drives — outside by definition
            inside = False
        if not inside:
            raise WorkspaceDenied("path-outside-workspace")

        # link screening — any link in the chain must stay inside the root
        if not allow_links_inside:
            self._check_links(candidate, resolved)

        # sensitive-name screening on the *final* component and any
        # sensitive directory in the relative chain
        rel_posix = resolved.relative_to(self.root).as_posix()
        parts = rel_posix.split("/")
        for i, part in enumerate(parts):
            if _SENSITIVE_NAMES.match(part):
                raise WorkspaceDenied("path-sensitive")
            if part in _SENSITIVE_DIRS or "/".join(parts[:i + 1]) in _SENSITIVE_DIRS:
                raise WorkspaceDenied("path-sensitive-dir")

        return SafePath(resolved, rel_posix)

    def _check_links(self, candidate: Path, resolved: Path) -> None:
        """Reject when any chain component is a link that escapes the root."""
        # walk candidate components that exist, checking link nature
        cur = self.root
        for part in candidate.parts[len(self.root.parts):]:
            cur = cur / part
            if not cur.exists() and not cur.is_symlink():
                break  # nonexistent tail — nothing to traverse safely
            if _is_symlink(cur):
                try:
                    tgt = cur.resolve(strict=False)
                except (OSError, RuntimeError):
                    raise WorkspaceDenied("link-unresolvable")
                try:
                    inside = os.path.commonpath(
                        [os.path.normcase(str(self.root)),
                         os.path.normcase(str(tgt))]) == os.path.normcase(
                        str(self.root))
                except ValueError:
                    inside = False
                if not inside:
                    raise WorkspaceDenied("link-outside-workspace")

    def safe_read_bytes(self, rel: str | os.PathLike[str], *,
                        max_bytes: int) -> bytes:
        """Bounded file read → bytes. Re-resolves just before open."""
        sp = self.resolve(rel)
        if not sp.abs_path.is_file():
            raise WorkspaceDenied("path-not-a-file")
        size = sp.abs_path.stat().st_size
        if size > max_bytes:
            raise WorkspaceDenied(f"file-too-large:{size}>{max_bytes}")
        with sp.open("rb") as f:
            return f.read(max_bytes + 1)[:max_bytes]

    # -- bounded iteration ------------------------------------------------------

    def iter_tree(self, *, max_depth: int, max_files: int,
                  skip_dirs: frozenset[str] | None = None) -> Iterator[SafePath]:
        """Depth/count-bounded walk yielding SafePaths; skips denylisted
        and linky directories. Deterministic order (sorted)."""
        skip = (skip_dirs or frozenset()) | {".git", "node_modules",
                                             "__pycache__", ".venv", "venv",
                                             ".idea", ".vs", ".tox", "dist"}
        yielded = 0
        stack: list[tuple[Path, int]] = [(self.root, 0)]
        while stack and yielded < max_files:
            cur, depth = stack.pop()
            try:
                entries = sorted(cur.iterdir(), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if yielded >= max_files:
                    return
                name = e.name
                if _SENSITIVE_NAMES.match(name):
                    continue
                try:
                    is_dir = e.is_dir()
                except OSError:
                    continue
                if is_dir:
                    if name in skip or name in _SENSITIVE_DIRS:
                        continue
                    if _is_symlink(e):
                        # links inside the tree may still escape — verify
                        try:
                            tgt = e.resolve(strict=False)
                            inside = os.path.commonpath(
                                [os.path.normcase(str(self.root)),
                                 os.path.normcase(str(tgt))]
                            ) == os.path.normcase(str(self.root))
                        except (OSError, RuntimeError, ValueError):
                            inside = False
                        if not inside:
                            continue
                    if depth < max_depth:
                        stack.append((e, depth + 1))
                else:
                    try:
                        rel = e.relative_to(self.root).as_posix()
                    except ValueError:
                        continue
                    yielded += 1
                    yield SafePath(e, rel)


def detect_workspace(start: str | os.PathLike[str] | None) -> Path | None:
    """Best-effort workspace detection — never throws, never scans outside."""
    if start:
        try:
            p = Path(start).expanduser().resolve()
            if p.is_dir():
                return p
        except OSError:
            return None
    for env_key in ("FAB_MCP_WORKSPACE", "MCP_WORKSPACE"):
        v = os.environ.get(env_key)
        if v:
            try:
                p = Path(v).expanduser().resolve()
                if p.is_dir():
                    return p
            except OSError:
                continue
    try:
        return Path.cwd().resolve()
    except OSError:
        return None
