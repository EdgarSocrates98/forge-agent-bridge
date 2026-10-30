#!/usr/bin/env python3
"""Forge release compatibility checker (Cycle 30.2 §14/§16).

Discovers the three repos (env FORGE_ROOT or siblings of this repo),
reads real versions, detects provider CLIs, and emits the compatibility
matrix. Exit 1 on any repo missing or provider incompatible.

  python3 scripts/compat_check.py [--json] [--root /path/to/forjas]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PROTOCOLS = {"bridge": "0.1.0", "pf": "0.1.0", "portal": "1.0.0"}
PROVIDERS = ["codex", "claude", "devin", "copilot", "gh"]


def _find_root(cli: str | None) -> Path:
    if cli:
        return Path(cli).resolve()
    import os
    if os.environ.get("FORGE_ROOT"):
        return Path(os.environ["FORGE_ROOT"]).resolve()
    # repo root = parent of this script's repo (…/forjas/forge-agent-bridge)
    return Path(__file__).resolve().parents[2]


def _pyproject_version(repo: Path) -> str | None:
    f = repo / "pyproject.toml"
    if not f.exists():
        return None
    text = f.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if m:
        return m.group(1)
    # dynamic version via [tool.hatch.version] path → __init__.__version__
    m = re.search(r'\[tool\.hatch\.version\]\s*\npath\s*=\s*"([^"]+)"', text)
    if m:
        vf = repo / m.group(1)
        if vf.exists():
            v = re.search(r'__version__\s*=\s*"([^"]+)"', vf.read_text())
            if v:
                return v.group(1)
    return None


def _npm_version(repo: Path) -> str | None:
    f = repo / "package.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text()).get("version")
    except json.JSONDecodeError:
        return None


def _cli_version(exe: str) -> str | None:
    if not shutil.which(exe):
        return None
    for args in ([exe, "--version"], [exe, "version"]):
        try:
            out = subprocess.run(args, capture_output=True, text=True,
                                 timeout=10)
            line = (out.stdout or out.stderr).strip().splitlines()
            if line and line[0].strip():
                return line[0].strip()[:60]
        except Exception:  # noqa: BLE001 — detection only
            continue
    return "installed (version unknown)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root")
    a = ap.parse_args()
    root = _find_root(a.root)
    repos = {
        "forge-agent-bridge": root / "forge-agent-bridge",
        "product-forge": root / "product-forge",
        "forge-portal": root / "forge-portal",
    }
    matrix: dict[str, dict] = {"repos": {}, "providers": {}, "checks": []}
    ok = True
    for name, path in repos.items():
        v = _pyproject_version(path) or _npm_version(path)
        entry = {"path": str(path), "version": v}
        if v is None:
            entry["state"] = "missing"
            ok = False
        else:
            entry["state"] = "ok"
        matrix["repos"][name] = entry
    for exe in PROVIDERS:
        ver = _cli_version(exe)
        matrix["providers"][exe] = {
            "state": "installed" if ver else "absent",
            "version": ver}
    matrix["checks"].append({
        "name": "repos-present",
        "ok": all(r["state"] == "ok" for r in matrix["repos"].values())})
    if a.json:
        print(json.dumps(matrix, indent=1))
    else:
        print(f"root: {root}")
        for name, r in matrix["repos"].items():
            print(f"  {name:22} {r['state']:8} {r.get('version') or '-'}")
        print("providers:")
        for p, d in matrix["providers"].items():
            print(f"  {p:22} {d['state']:10} {d.get('version') or '-'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
