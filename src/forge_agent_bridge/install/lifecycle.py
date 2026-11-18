"""forge-bridge install lifecycle — bridge-honest install semantics.

Unlike content forges (product-forge/sparkforge-aws), the bridge ships no
host payloads — it is a localhost service. Its install components are the
real things the service needs: a state root, pairing token, provider
detection snapshot, seeded config, and a verified CLI launcher.

Same UX contract as `productforge install`: scope -> profile -> components
-> plan -> apply -> doctor. Nothing is faked — a component that cannot be
verified lands in `unverified`, never `applied`.

Receipt contract (install-2.1): `forge/InstallReceipt/v1` — the schema the
the-forge delegation verifier reads (`forge_id` + `operation="install"` +
`status` + `verification.status="PASS"`). Bridge-specific detail rides in
extra fields (`plan`, `applied`, `unverified`, `skipped`, `state_dir`, …);
the pair TOKEN is never one of them — only its path and hashes.

`--root` semantics: the CLI flag is the install TARGET root (the-forge
delegates `--root <workspace>`); state always lives under
`<target>/.forge-bridge` — never loose files at the target root. At this
API layer ``root`` is the already-resolved *state* directory, so
``bridge.install(root=Path("~/.forge-bridge").expanduser())`` keeps its
established meaning for in-process callers (product-forge provisioning).
``state_dir_under()`` is the target→state translation the CLI applies.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import time
from datetime import UTC, datetime
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

SCHEMA_RECEIPT = "forge/InstallReceipt/v1"
_SCHEMA_DOCTOR = "forge/BridgeDoctorReport/v1"
_SCHEMA_LEDGER = "forge/BridgeInstallLedger/v1"

# State-dir name used under every install target — matches the runtime
# convention (`~/.forge-bridge`, local_bridge.resolve_state_dir()).
STATE_DIR_NAME = ".forge-bridge"

# Install-managed artifacts that survive `uninstall`: the pair token is a
# credential (rotating/deleting it would break paired devices silently) and
# .gitignore keeps the preserved token out of any enclosing VCS.
_UNINSTALL_KEEP = frozenset({"pair.token", ".gitignore"})


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_dir_under(root: Path) -> Path:
    """Target root → bridge state dir (``<root>/.forge-bridge``).

    A path already naming the state dir is idempotent — passing
    ``~/.forge-bridge`` never yields ``~/.forge-bridge/.forge-bridge``."""
    root = Path(root)
    return root if root.name == STATE_DIR_NAME else root / STATE_DIR_NAME


def _root_for(scope: str, root: Path | None) -> Path:
    if root is not None:
        return root
    if scope == "project":
        return Path.cwd() / STATE_DIR_NAME
    if scope == "workspace":
        return Path.cwd().parent / STATE_DIR_NAME
    from ..local_bridge import resolve_state_dir
    return resolve_state_dir()


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
        steps.append({"component": "state",
                      "action": "write-if-absent",
                      "target": str(root / ".gitignore")})
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


# Managed-file kinds for `forge/InstallReceipt/v1` — closed enum:
# config|skill|agent|marker|mcp|state|launcher (see the-forge contract).
_MANAGED_KIND = {
    ".gitignore": "config",
    "config.json": "config",
    "pair.token": "state",
    "providers.json": "state",
    "components.json": "state",
}


def _write_if_absent(path: Path, content: str, mode: int) -> str:
    if path.exists():
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, mode)
    return "written"


def _rel(state_dir: Path, path: Path) -> str:
    """Receipt path relative to the target root (state_dir's parent)."""
    try:
        return path.relative_to(state_dir.parent).as_posix()
    except ValueError:
        return path.name


def install(*, scope: str = "user", profile: str = "recommended",
            components: tuple[str, ...] | None = None,
            root: Path | None = None, dry_run: bool = False,
            yes: bool = False, host: str | None = None,
            gateway_profile: str | None = None) -> dict[str, Any]:
    """Plan (dry_run) or apply the bridge install. Returns a receipt.

    ``root`` is the resolved bridge *state* directory (the ``.forge-bridge``
    dir itself) — the CLI maps the delegated ``--root <target>`` onto
    ``<target>/.forge-bridge`` before calling. ``host``/``gateway_profile``
    are accepted and honestly ignored: a service forge installs no host
    payloads and runs no execution profile.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} (valid: {list(SCOPES)})")
    if profile not in PROFILES:
        raise ValueError(
            f"unknown profile {profile!r} (valid: {list(PROFILES)})")
    comps = _profile_components(profile, components)
    root_dir = _root_for(scope, root)
    steps = _plan(root_dir, comps)
    target_root = str(root_dir.parent)

    receipt: dict[str, Any] = {
        "schema": SCHEMA_RECEIPT,
        "forge_id": "forge-agent-bridge",
        "operation": "install",
        "scope": scope,
        "profile": profile,
        "components": {"selected": list(comps)},
        "target_root": target_root,
        # a service forge installs no host payloads — recorded, never claimed
        "host": None,
        "dry_run": dry_run,
        "managed_files": [],
        "managed_markers": [],
        "mcp": [],
        "env": {"python": platform.python_version()},
        "checks": [],
        "verification": {"status": "UNVERIFIED"},
        "status": "planned",
        "created_at": _utc_now(),
        "created_by": f"forge-agent-bridge/{__version__}",
        # -- bridge extras -------------------------------------------------
        "version": __version__,
        "state_dir": str(root_dir),
        "root": str(root_dir),  # legacy alias of state_dir
        "components_selected": list(comps),
        "plan": steps,
        "planned_files": [
            {"path": _rel(root_dir, Path(s["target"])),
             "kind": _MANAGED_KIND.get(Path(s["target"]).name, "state"),
             "action": "preserve" if Path(s["target"]).exists() else "create",
             "sha256": _sha_file(Path(s["target"]))
             if Path(s["target"]).is_file() else ""}
            for s in steps
            if s["action"] in ("write-if-absent-0600", "write-snapshot",
                               "write-if-absent", "write")
        ] if dry_run else [],
        "applied": [], "unverified": [], "skipped": [],
        "yes": yes,
        "requested_host": host,
        "requested_gateway_profile": gateway_profile,
        "notes": ([
            "installation_kind=service — no host payloads; state only",
            ("scoped state roots are served via FAB_STATE_DIR or "
             "`forge-bridge serve --state-dir`"),
        ] if scope != "user" else [
            "installation_kind=service — no host payloads; state only"]),
    }
    if host is not None or gateway_profile is not None:
        receipt["checks"].append({
            "id": "host-gateway-args",
            "status": "NOT_APPLICABLE",
            "detail": "service forge — --host/--gateway-profile accepted "
                      "and ignored (no host payloads, no execution profile)"})
    if dry_run:
        receipt["receipt_id"] = "sha256:" + hashlib.sha256(
            json.dumps(steps, sort_keys=True).encode()).hexdigest()
        return receipt

    applied, unverified, skipped = [], [], []
    managed: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = list(receipt["checks"])
    ledger_files: list[dict[str, Any]] = []

    def _managed(path: Path, action: str) -> None:
        managed.append({"path": _rel(root_dir, path),
                        "sha256": _sha_file(path),
                        "kind": _MANAGED_KIND.get(path.name, "state"),
                        "action": action})

    for s in steps:
        comp, action, target = s["component"], s["action"], s["target"]
        try:
            if action == "verify-cli":
                exe = shutil.which("forge-bridge")
                if exe:
                    applied.append({**s, "result": exe})
                    checks.append({"id": "component:service",
                                   "status": "PASS",
                                   "detail": f"forge-bridge → {exe}"})
                else:
                    unverified.append({
                        **s,
                        "result": "unverified:forge-bridge not on PATH "
                                  "(run install.sh/bootstrap first)"})
                    checks.append({"id": "component:service",
                                   "status": "UNVERIFIED",
                                   "detail": "forge-bridge not on PATH"})
                continue
            if action == "mkdir":
                Path(target).mkdir(parents=True, exist_ok=True)
                applied.append({**s, "result": "ok"})
                checks.append({"id": f"mkdir:{Path(target).name}",
                               "status": "PASS", "detail": target})
                continue
            if action == "write-if-absent-0600":
                p = Path(target)
                if p.exists():
                    skipped.append({**s, "result": "exists"})
                    _managed(p, "unchanged")
                    ledger_files.append({"path": p.name,
                                         "state": "preserved"})
                    checks.append({"id": f"file:{p.name}",
                                   "status": "PASS",
                                   "detail": "preserved existing "
                                             "(never rotated silently)"})
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(secrets.token_urlsafe(32))
                    os.chmod(target, 0o600)
                    applied.append({**s, "result": "written (0600)"})
                    _managed(p, "created")
                    ledger_files.append({"path": p.name,
                                         "state": "created"})
                    checks.append({"id": f"file:{p.name}",
                                   "status": "PASS",
                                   "detail": "written 0600"})
                continue
            if action == "write-snapshot":
                from ..registry import REGISTRY
                snap = [d.model_dump(mode="json")
                        for d in REGISTRY.detect_all()]
                p = Path(target)
                p.parent.mkdir(parents=True, exist_ok=True)
                existed = p.exists()
                p.write_text(json.dumps(
                    {"detected_at": time.time(), "providers": snap},
                    indent=1))
                applied.append({**s,
                                "result": f"{len(snap)} providers detected"})
                _managed(p, "updated" if existed else "created")
                ledger_files.append({"path": p.name, "state": "managed"})
                checks.append({"id": f"file:{p.name}", "status": "PASS",
                               "detail": f"{len(snap)} providers detected"})
                continue
            if action == "write-if-absent":
                p = Path(target)
                content = ("*\n" if p.name == ".gitignore"
                           else json.dumps(DEFAULT_CONFIG, indent=1))
                r = _write_if_absent(p, content, 0o600)
                if r == "exists":
                    skipped.append({**s, "result": r})
                    _managed(p, "unchanged")
                    ledger_files.append({"path": p.name,
                                         "state": "preserved"})
                    checks.append({"id": f"file:{p.name}", "status": "PASS",
                                   "detail": "preserved existing "
                                             "(user file — not adopted)"})
                else:
                    applied.append({**s, "result": r})
                    _managed(p, "created")
                    ledger_files.append({"path": p.name,
                                         "state": "created"})
                    checks.append({"id": f"file:{p.name}", "status": "PASS",
                                   "detail": "written"})
                continue
            if action == "write" and comp == "ledger":
                p = Path(target)
                existed = p.exists()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(
                    {"schema": _SCHEMA_LEDGER,
                     "forge": "forge-agent-bridge", "version": __version__,
                     "scope": scope, "profile": profile,
                     "components": list(comps),
                     "state_dir": str(root_dir),
                     "installed_at": time.time(),
                     "files": ledger_files}, indent=1))
                applied.append({**s, "result": "written"})
                _managed(p, "updated" if existed else "created")
                checks.append({"id": "ledger", "status": "PASS",
                               "detail": "components.json written"})
                continue
            skipped.append({**s, "result": "no-handler"})
        except OSError as e:
            unverified.append({**s, "result": f"unverified:{e}"})
            checks.append({"id": f"{comp}:{action}", "status": "UNVERIFIED",
                           "detail": str(e)})

    failed = [c for c in checks if c["status"] == "FAIL"]
    uncertain = [c for c in checks if c["status"] == "UNVERIFIED"]
    receipt["applied"] = applied
    receipt["unverified"] = unverified
    receipt["skipped"] = skipped
    receipt["managed_files"] = managed
    receipt["checks"] = checks
    receipt["verification"] = {
        "status": "FAIL" if failed else
                  "UNVERIFIED" if uncertain else "PASS"}
    receipt["status"] = "completed"
    receipt["installed_at"] = time.time()
    receipt["receipt_id"] = (
        "sha256:" + hashlib.sha256(json.dumps(
            {"f": managed}, sort_keys=True).encode()).hexdigest())
    _write_receipt(root_dir, receipt)
    return receipt


def _write_receipt(state_dir: Path, receipt: dict[str, Any]) -> Path:
    """`<state>/receipts/install-<ts>.json` — the `.<state>/receipts`
    convention the-forge scans when stdout carries no receipt."""
    ts = receipt["created_at"].replace(":", "").replace("-", "")
    path = state_dir / "receipts" / f"install-{ts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    return path


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
    n_exec = sum(1 for d in det if d.executable)
    checks.append({"check": "providers-detected",
                   "state": f"{n_exec}/{len(det)} executables"})
    ledger = root_dir / "components.json"
    checks.append({"check": "ledger", "target": str(ledger),
                   "state": "ok" if ledger.exists() else "missing"})

    def _accept(state: Any) -> bool:
        s = str(state)
        if s == "ok":
            return True
        if s.endswith("executables"):
            head = s.split("/", 1)[0]
            return head.isdigit() and int(head) > 0
        if s in ("missing",) or s.startswith(("warn:", "unverified")):
            return False
        return os.path.isabs(s)  # resolved executable path

    ok = all(_accept(c["state"]) for c in checks)
    return {"schema": _SCHEMA_DOCTOR,
            "forge_id": "forge-agent-bridge",
            "root": str(root_dir), "state_dir": str(root_dir),
            "target_root": str(root_dir.parent),
            "scope": scope, "checks": checks,
            "checked_at": _utc_now(),
            "overall": "ok" if ok else "incomplete",
            "status": "healthy" if ok else "degraded"}


def _ledger_removal_plan(root_dir: Path) -> tuple[list[str], str]:
    """Files this install owns and may remove — from the ledger, never a
    hard-coded guess. Returns (relpaths, provenance-note)."""
    ledger = root_dir / "components.json"
    if not ledger.exists():
        return [], ("no install ledger — nothing recorded as "
                    "install-owned; state left intact")
    try:
        doc = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], ("unreadable ledger — nothing removed "
                    "(provenance unverifiable)")
    files = doc.get("files")
    if not isinstance(files, list):
        # Legacy ledger (pre files[] inventory): providers.json and the
        # ledger itself are always install-generated; config.json's
        # provenance is unrecorded — kept rather than guessed.
        return (["providers.json", "components.json"],
                ("legacy ledger without files[] — removed only "
                 "always-generated artifacts; config.json kept "
                 "(provenance unrecorded)"))
    out = ["components.json"]
    for f in files:
        if not isinstance(f, dict):
            continue
        name = str(f.get("path") or "")
        state = str(f.get("state") or "")
        if name and state in ("created", "managed") \
                and name not in _UNINSTALL_KEEP:
            out.append(name)
    return out, "ledger files[] inventory"


def uninstall(*, scope: str = "user", root: Path | None = None,
              yes: bool = False) -> dict[str, Any]:
    """Remove only files the install ledger recorded as install-owned —
    NEVER pair.token, events/, backups/, or any user/runtime state
    (sessions.json, pairing.json, audit.jsonl, secrets.json,
    provider-work/, receipts/). ``kept`` enumerates what remains."""
    root_dir = _root_for(scope, root)
    removed, kept = [], []
    targets, provenance = _ledger_removal_plan(root_dir)
    for rel in targets:
        p = root_dir / rel
        if p.exists() and p.is_file():
            p.unlink()
            removed.append(rel)
    if root_dir.is_dir():
        for entry in sorted(root_dir.iterdir()):
            name = entry.name + ("/" if entry.is_dir() else "")
            if entry.name not in {r for r in removed}:
                kept.append(name)
    receipt: dict[str, Any] = {
        "schema": SCHEMA_RECEIPT,
        "forge_id": "forge-agent-bridge",
        "operation": "uninstall",
        "scope": scope,
        "target_root": str(root_dir.parent),
        "dry_run": False,
        "managed_files": [{"path": _rel(root_dir, root_dir / r),
                           "sha256": "", "kind": "state",
                           "action": "removed"} for r in removed],
        "checks": [{"id": "ledger-removal", "status": "PASS",
                    "detail": f"{len(removed)} install-owned file(s) "
                              f"removed ({provenance})"}],
        "verification": {"status": "PASS"},
        "status": "completed",
        "created_at": _utc_now(),
        "created_by": f"forge-agent-bridge/{__version__}",
        # -- bridge extras -------------------------------------------------
        "version": __version__,
        "state_dir": str(root_dir),
        "root": str(root_dir),  # legacy alias of state_dir
        "removed": removed,
        "kept": kept,
        "notes": [
            ("state (pair.token/events/backups/runtime files) preserved — "
             "delete the state dir manually only if a purge is intended"),
            provenance],
    }
    receipt["receipt_id"] = (
        "sha256:" + hashlib.sha256(json.dumps(
            {"r": removed, "k": kept}, sort_keys=True).encode()).hexdigest())
    return receipt
