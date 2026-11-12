"""forge_workspace_summary + forge_architecture_review (stdlib-only)."""

from __future__ import annotations

import os
import time
from typing import Any

from ..workspace import WorkspaceDenied

_LANG_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".go": "go",
    ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".md": "markdown", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".sh": "shell",
    ".ps1": "powershell", ".html": "html", ".css": "css",
}
_MANIFESTS = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "uv.lock", "Pipfile", "poetry.lock",
    "forge.json", "forge.agentic.json", "workspace.yaml", "AGENTS.md",
    "CLAUDE.md", "CONTEXT.md", ".mcp.json",
})
_CI_HINTS = (".github/workflows", ".gitlab-ci.yml", "azure-pipelines.yml",
             "Jenkinsfile", ".circleci")
_TEST_DIRS = ("tests", "test", "spec", "e2e")


def _require_guard(ctx: Any):
    if ctx.guard is None:
        raise WorkspaceDenied("no-workspace-authorized")
    return ctx.guard


def summary(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
    t0 = time.monotonic()
    guard = _require_guard(ctx)
    depth = min(int(args.get("max_depth") or ctx.policy.workspace_read_depth),
                ctx.policy.workspace_read_depth)
    top_dirs: list[str] = []
    langs: dict[str, int] = {}
    manifests: list[str] = []
    contracts: list[str] = []
    files_seen = 0
    truncated = False
    for sp in guard.iter_tree(max_depth=depth,
                            max_files=ctx.policy.max_scan_files):
        files_seen += 1
        rel = sp.rel_posix
        parts = rel.split("/")
        if len(parts) > 1 and parts[0] not in top_dirs:
            top_dirs.append(parts[0])
        ext = os.path.splitext(sp.abs_path.name)[1].lower()
        if ext in _LANG_BY_EXT:
            langs[_LANG_BY_EXT[ext]] = langs.get(_LANG_BY_EXT[ext], 0) + 1
        if sp.abs_path.name in _MANIFESTS:
            manifests.append(rel)
            if sp.abs_path.name.startswith("forge."):
                contracts.append(rel)
    truncated = files_seen >= ctx.policy.max_scan_files

    git_present = (guard.root / ".git").exists()
    primary = sorted(langs.items(), key=lambda kv: -kv[1])[:5]
    return {
        "workspace": str(guard.root),
        "git": {"present": git_present,
                "note": None if git_present
                else "absent — git-dependent features report unavailable"},
        "top_level_dirs": top_dirs[:40],
        "languages_detected": dict(primary),
        "files_scanned": files_seen,
        "scan_truncated": truncated,
        "manifests": manifests[:60],
        "forge_contracts": contracts,
        "limits": {"depth": depth, "max_files": ctx.policy.max_scan_files,
                   "elapsed_ms": round((time.monotonic() - t0) * 1000, 1)},
        "warnings": (["scan hit file cap — results partial"] if truncated
                     else []),
    }


def architecture_review(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
    guard = _require_guard(ctx)
    findings: list[dict[str, Any]] = []
    evid = []
    root_names = set()
    manifests = []
    for sp in guard.iter_tree(max_depth=ctx.policy.workspace_read_depth,
                              max_files=ctx.policy.max_scan_files):
        rel = sp.rel_posix
        if "/" not in rel:
            root_names.add(rel)
        if sp.abs_path.name in _MANIFESTS:
            manifests.append(rel)
            evid.append(f"manifest:{rel}")

    def check(ok: bool, fid: str, msg: str, sev: str, evidence: list[str]):
        findings.append({"id": fid, "status": "pass" if ok else "warn",
                         "severity": sev if not ok else "info",
                         "detail": msg, "evidence": evidence[:6],
                         "confidence": "verified-rule"})

    has_tests = any(d in root_names for d in _TEST_DIRS) or any(
        any(seg in _TEST_DIRS for seg in m.split("/")) for m in manifests)
    check(has_tests, "tests-present",
          "test layout detected" if has_tests
          else "no conventional test directory detected at scan depth",
          "medium", evid[:4])
    has_ci = any(h.split("/")[0] in root_names or h in root_names
                 for h in _CI_HINTS) or (guard.root / ".github" / "workflows").is_dir()
    check(has_ci, "ci-present",
          "CI configuration detected" if has_ci
          else "no CI configuration detected",
          "low", evid[:4])
    check("forge.json" in root_names or any(m.endswith("forge.json") for m in manifests),
          "forge-contract",
          "forge.json present" if any(m.endswith("forge.json") for m in manifests)
          else "no forge.json manifest detected",
          "info", [m for m in manifests if m.endswith(".json")][:4])
    has_lock = any(m.endswith((".lock", "lock.yaml", "-lock.json"))
                   for m in manifests)
    check(has_lock, "deps-pinned",
          "dependency lockfile present" if has_lock
          else "no dependency lockfile detected — reproducibility unverified",
          "medium", [m for m in manifests if "lock" in m][:4])
    has_rules = bool({"AGENTS.md", "CLAUDE.md", "CONTEXT.md"} & root_names)
    check(has_rules, "agent-rules",
          "agent instruction files present" if has_rules
          else "no AGENTS/CLAUDE/CONTEXT instruction file",
          "info", [n for n in root_names if n.endswith(".md")][:4])

    return {
        "workspace": str(guard.root),
        "method": "deterministic-rule-checks",
        "method_limits": ("static structure only — no semantic analysis, "
                          "no dependency resolution, no execution"),
        "findings": findings,
        "counts": {"pass": sum(1 for f in findings if f["status"] == "pass"),
                   "warn": sum(1 for f in findings if f["status"] == "warn")},
        "manifests_seen": manifests[:30],
    }
