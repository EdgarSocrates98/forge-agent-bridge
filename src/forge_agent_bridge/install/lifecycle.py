"""forge-bridge install lifecycle — bridge-honest install semantics.

Unlike content forges (product-forge/sparkforge-aws), the bridge ships no
host payloads — it is a localhost service. Its install components are the
real things the service needs: a state root, pairing token, provider
detection snapshot, seeded config, and a verified CLI launcher.

Same UX contract as `productforge install`: scope -> profile -> components
-> plan -> apply -> doctor. Nothing is faked — a component that cannot be
verified lands in `unverified`, never `applied`.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import time
from pathlib import Path
from typing import Any

from .. import __version__

SCOPES = ("project", "workspace", "user")
PROFILES = ("minimal", "recommended", "full")

# honest component vocabulary for a localhost service (no skills/hosts)
COMPONENTS = ("service", "state", "pairing", "providers", "config")
PROFILE_COMPONENTS = {
    "minimal": ("state",),
    "recommended": ("service", "state", "pairing", "providers"),
    "full": ("service", "state", "pairing", "providers", "config"),
}

DEFAULT_CONFIG = {
    "rate_limit_per_min": 240,
    "runner_quota": 8,
    "event_retention_per_session": 5000,
    "session_token_ttl_s": 86400,
    "nonce_window_s": 300,
}


def _root_for(scope: str, root: Path | None) -> Path:
    if root is not None:
        return root
    if scope == "project":
        return Path.cwd() / ".forge-bridge"
    if scope == "workspace":
        return Path.cwd().parent / ".forge-bridge"
    return Path.home() / ".forge-bridge"


def _profile_components(profile: str,
                        components: tuple[str, ...] | None) -> tuple[str, ...]:
    if components:
        unknown = [c for c in components if c not in COMPONENTS]
        if unknown:
            raise ValueError(f"unknown components: {unknown} "
                             f"(valid: {list(COMPONENTS)})")
        return components
    return PROFILE_COMPONENTS.get(profile, PROFILE_COMPONENTS["recommended"])


def _plan(root: Path, comps: tuple[str, ...]) -> list[dict[str, Any]]:
    """Deterministic plan — the same entries apply() will produce."""
    steps: list[dict[str, Any]] = []
    if "service" in comps:
        steps.append({"component": "service", "action": "verify-cli",
                      "target": "forge-bridge on PATH"})
    if "state" in comps:
        steps.append({"component": "state", "action": "mkdir",
                      "target": str(root)})
        steps.append({"component": "state", "action": "mkdir",
                      "target": str(root / "events")})
        steps.append({"component": "state", "action": "mkdir",
                      "target": str(root / "backups")})
    if "pairing" in comps:
        steps.append({"component": "pairing",
                      "action": "write-if-absent-0600",
                      "target": str(root / "pair.token")})
    if "providers" in comps:
        steps.append({"component": "providers",
                      "action": "write-snapshot",
                      "target": str(root / "providers.json")})
    if "config" in comps:
        steps.append({"component": "config",
                      "action": "write-if-absent",
                      "target": str(root / "config.json")})
    steps.append({"component": "ledger", "action": "write",
                  "target": str(root / "components.json")})
    return steps


def _write_if_absent(path: Path, content: str, mode: int) -> str:
    if path.exists():
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, mode)
    return "written"


def install(*, scope: str = "user", profile: str = "recommended",
            components: tuple[str, ...] | None = None,
            root: Path | None = None, dry_run: bool = False,
            yes: bool = False) -> dict[str, Any]:
    """Plan (dry_run) or apply the bridge install. Returns a receipt."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} (valid: {list(SCOPES)})")
    if profile not in PROFILES:
        raise ValueError(
            f"unknown profile {profile!r} (valid: {list(PROFILES)})")
    comps = _profile_components(profile, components)
    root_dir = _root_for(scope, root)
    steps = _plan(root_dir, comps)

    receipt: dict[str, Any] = {
        "schema": "forge/BridgeInstallReceipt/v1",
        "forge": "forge-agent-bridge", "version": __version__,
        "scope": scope, "profile": profile, "components": list(comps),
        "root": str(root_dir), "dry_run": dry_run, "yes": yes,
        "plan": steps, "applied": [], "unverified": [], "skipped": [],
        "installed_at": None,
    }
    if dry_run:
        return receipt

    applied, unverified, skipped = [], [], []
    for s in steps:
        comp, action, target = s["component"], s["action"], s["target"]
        try:
            if action == "verify-cli":
                exe = shutil.which("forge-bridge")
                if exe:
                    applied.append({**s, "result": exe})
                else:
                    unverified.append({
                        **s,
                        "result": "unverified:forge-bridge not on PATH "
                                  "(run install.sh/bootstrap first)"})
                continue
            if action == "mkdir":
                Path(target).mkdir(parents=True, exist_ok=True)
                applied.append({**s, "result": "ok"})
                continue
            if action == "write-if-absent-0600":
                if Path(target).exists():
                    skipped.append({**s, "result": "exists"})
                else:
                    Path(target).parent.mkdir(parents=True, exist_ok=True)
                    Path(target).write_text(secrets.token_urlsafe(32))
                    os.chmod(target, 0o600)
                    applied.append({**s, "result": "written (0600)"})
                continue
            if action == "write-snapshot":
                from ..registry import REGISTRY
                snap = [d.model_dump(mode="json")
                        for d in REGISTRY.detect_all()]
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_text(json.dumps(
                    {"detected_at": time.time(), "providers": snap},
                    indent=1))
                applied.append({**s,
                                "result": f"{len(snap)} providers detected"})
                continue
            if action == "write-if-absent":
                r = _write_if_absent(Path(target),
                                     json.dumps(DEFAULT_CONFIG, indent=1),
                                     0o600)
                (skipped if r == "exists" else applied).append(
                    {**s, "result": r})
                continue
            if action == "write" and comp == "ledger":
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_text(json.dumps(
                    {"forge": "forge-agent-bridge", "version": __version__,
                     "scope": scope, "profile": profile,
                     "components": list(comps),
                     "installed_at": time.time()}, indent=1))
                applied.append({**s, "result": "written"})
                continue
            skipped.append({**s, "result": "no-handler"})
        except OSError as e:
            unverified.append({**s, "result": f"unverified:{e}"})

    receipt["applied"] = applied
    receipt["unverified"] = unverified
    receipt["skipped"] = skipped
    receipt["installed_at"] = time.time()
    return receipt


def doctor(*, scope: str = "user", root: Path | None = None) -> dict[str, Any]:
    """Verify an install — honest per-check states."""
    root_dir = _root_for(scope, root)
    checks: list[dict[str, Any]] = []

    checks.append({"check": "state-root", "target": str(root_dir),
                   "state": "ok" if root_dir.is_dir() else "missing"})
    pt = root_dir / "pair.token"
    if pt.exists():
        mode = stat.S_IMODE(pt.stat().st_mode)
        checks.append({"check": "pair-token-mode", "target": str(pt),
                       "state": "ok" if mode == 0o600 else f"warn:{oct(mode)}"})
    else:
        checks.append({"check": "pair-token", "target": str(pt),
                       "state": "missing"})
    for d in ("events", "backups"):
        checks.append({"check": f"dir:{d}", "target": str(root_dir / d),
                       "state": "ok" if (root_dir / d).is_dir()
                       else "missing"})
    exe = shutil.which("forge-bridge")
    checks.append({"check": "cli-on-path", "target": "forge-bridge",
                   "state": exe or "unverified:not-on-path"})

    from ..registry import REGISTRY
    det = REGISTRY.detect_all()
    checks.append({"check": "providers-detected",
                   "state": f"{sum(1 for d in det if d.executable)}"
                            f"/{len(det)} executables"})
    ledger = root_dir / "components.json"
    checks.append({"check": "ledger", "target": str(ledger),
                   "state": "ok" if ledger.exists() else "missing"})

    ok = all(c["state"] in ("ok",) or "/4" in str(c["state"])
             or "forge-agent-bridge" in str(c["state"])
             or str(c["state"]).startswith("/")
             or c["state"].endswith("executables") for c in checks)
    return {"schema": "forge/BridgeDoctorReport/v1", "root": str(root_dir),
            "scope": scope, "checks": checks,
            "overall": "ok" if ok else "incomplete"}


def uninstall(*, scope: str = "user", root: Path | None = None,
              yes: bool = False) -> dict[str, Any]:
    """Remove only generated files in the ledger — NEVER pair.token,
    events/, backups/, or any user state (honest: state preserved)."""
    root_dir = _root_for(scope, root)
    removed, kept = [], []
    for f in ("providers.json", "config.json", "components.json"):
        p = root_dir / f
        if p.exists():
            p.unlink()
            removed.append(str(p))
    for keep in ("pair.token", "events", "backups"):
        if (root_dir / keep).exists():
            kept.append(str(root_dir / keep))
    return {"schema": "forge/BridgeUninstallReceipt/v1",
            "root": str(root_dir), "removed": removed,
            "kept": kept,
            "note": "state (pair.token/events/backups) preserved — "
                    "delete manually if a purge is intended"}
