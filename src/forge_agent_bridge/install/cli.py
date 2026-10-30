"""`forge-bridge install` — guided wizard (TTY) + flag path (JSON).

Same UX contract as `productforge install` / `sparkforge-aws install`:
scope -> install profile -> components -> real dry-run plan -> confirm ->
apply -> doctor. Bridge-honest differences: no host payloads and no
gateway profile (a localhost service, not a content forge).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import lifecycle


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _emit(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _ask(prompt: str, options: list[str], default: str) -> str:
    print(f"\n{prompt}")
    for i, o in enumerate(options, 1):
        mark = "*" if o == default else " "
        print(f"  [{i}]{mark} {o}")
    raw = input(f"choose [default={default}]: ").strip()
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    if raw in options:
        return raw
    print(f"  invalid {raw!r} — using {default}")
    return default


def _ask_multi(prompt: str, options: tuple[str, ...],
               default: tuple[str, ...]) -> tuple[str, ...]:
    print(f"\n{prompt} (comma-separated numbers, or 'all')")
    for i, o in enumerate(options, 1):
        mark = "*" if o in default else " "
        print(f"  [{i}]{mark} {o}")
    raw = input(f"choose [default={','.join(default)}]: ").strip()
    if not raw:
        return default
    if raw == "all":
        return options
    picks: list[str] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(options):
            picks.append(options[int(tok) - 1])
        elif tok in options:
            picks.append(tok)
    return tuple(dict.fromkeys(picks)) or default


def run_guided_install() -> int:
    """Interactive wizard — mirrors the product-forge step contract."""
    print("=" * 60)
    print(" Forge Agent Bridge — guided install")
    print(" localhost service: pair token, state root, provider snapshot")
    print("=" * 60)

    scope = _ask("Install scope (state root location):",
                 ["user", "project", "workspace"], "user")
    profile = _ask("Install profile:", list(lifecycle.PROFILES),
                   "recommended")
    comps = _ask_multi("Components:", lifecycle.COMPONENTS,
                       lifecycle.PROFILE_COMPONENTS[profile])
    print("\n  hosts: none — the bridge is a localhost service "
          "(no host payloads)")

    plan = lifecycle.install(scope=scope, profile=profile,
                             components=comps, dry_run=True)
    print("\n--- plan (dry run) ---")
    for s in plan["plan"]:
        print(f"  {s['component']:<10} {s['action']:<22} {s['target']}")

    if input("\napply? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("aborted — nothing written")
        return 1

    receipt = lifecycle.install(scope=scope, profile=profile,
                                components=comps, yes=True)
    print(f"\napplied: {len(receipt['applied'])} · "
          f"skipped: {len(receipt['skipped'])} · "
          f"unverified: {len(receipt['unverified'])}")
    for u in receipt["unverified"]:
        print(f"  unverified: {u['component']} — {u['result']}")

    doc = lifecycle.doctor(scope=scope)
    print(f"\ndoctor: {doc['overall']}")
    for c in doc["checks"]:
        print(f"  {c['check']:<22} {c['state']}")
    print("\nnext: forge-bridge doctor · "
          "forge-bridge install --help")
    return 0


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
