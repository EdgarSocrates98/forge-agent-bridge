"""`forge-bridge install` — guided wizard (TTY) + flag path (JSON).

Same UX contract as `productforge install` / `sparkforge-aws install`:
the shared ui/kit wizard drives scope -> install profile -> components
-> real dry-run plan -> confirm -> apply -> doctor, every step
cancellable with Esc/q. Bridge-honest differences: no host payloads
and no gateway profile (a localhost service, not a content forge), so
those steps are skipped by passing empty vocabularies to the wizard.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import lifecycle

_COMPONENT_LABELS = {
    "service": "Service",
    "state": "State",
    "pairing": "Pairing",
    "providers": "Providers",
    "config": "Config",
}
_COMPONENT_DETAILS = {
    "service": "verify the forge-bridge CLI is reachable on PATH",
    "state": "state root with events/ and backups/ directories",
    "pairing": "pair.token written with 0600 permissions",
    "providers": "detected provider snapshot (providers.json)",
    "config": "default config.json written if absent",
}


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _install(**kw: Any) -> dict[str, Any]:
    """Map the wizard's keyword contract onto the real lifecycle.

    ``host``/``gateway_profile`` are accepted and ignored — the bridge
    installs no host payloads and has no execution profile.
    """
    receipt = lifecycle.install(
        scope=kw.get("scope", "user"),
        profile=kw.get("profile", "recommended"),
        components=kw.get("components"),
        dry_run=bool(kw.get("dry_run")),
        yes=bool(kw.get("yes")),
    )
    # The receipt schema has no lifecycle status; the wizard's
    # completed/planned channel is added here, not in the stored doc.
    if kw.get("dry_run"):
        return {**receipt, "status": "planned"}
    return {**receipt, "status": "completed"}


def _doctor(**kw: Any) -> dict[str, Any]:
    doc = lifecycle.doctor(scope=kw.get("scope", "user"))
    return {"status": "healthy" if doc.get("overall") == "ok" else "degraded"}


def run_guided_install() -> int:
    """Interactive wizard via the vendored ui/kit — arrow-key menus."""
    from ..ui.kit import UIContext
    from ..ui.wizard import run_wizard

    return run_wizard(
        forge_name="forge-agent-bridge",
        install_fn=_install,
        doctor_fn=_doctor,
        hosts_available=(),
        gateway_profiles=(),
        scopes=("user", "project", "workspace"),
        component_order=lifecycle.COMPONENTS,
        component_labels=_COMPONENT_LABELS,
        component_details=_COMPONENT_DETAILS,
        component_defaults={
            p: set(c) for p, c in lifecycle.PROFILE_COMPONENTS.items()
        },
        env_hosts=(),
        next_hint="forge-bridge doctor · forge-bridge install-status",
        ctx=UIContext.detect(),
    )


def run_flag_install(*, scope: str, profile: str,
                     components: str | None, root: str | None,
                     dry_run: bool, yes: bool) -> dict[str, Any]:
    comps = (tuple(c.strip() for c in components.split(",") if c.strip())
             if components else None)
    return lifecycle.install(
        scope=scope, profile=profile, components=comps,
        root=Path(root) if root else None,
        dry_run=dry_run, yes=yes)


def guided_install_available() -> bool:
    return _tty()
