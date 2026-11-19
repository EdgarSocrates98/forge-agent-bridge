# Cycle 16.1 — Wave 08 · forge-agent-bridge — run report

Spec: `factory/specs/inbox/cycle16_1-wave08-forge-agent-bridge.md`
Master prompt: `prompt_evo_forjas2.0.1.md` §13 ONDA 08, §5.3, §7.2/§7.4,
§9, §14.
Branch: `cycle16_1/wave08` · baseline `34d65b7` (main, clean).
Result: **DONE** (real delta — not NO_CHANGE).

## Scope verdicts

| Requirement | Status | Evidence |
|---|---|---|
| Receipts/status compatible with `forge/InstallLifecycle/v1` | DONE | every receipt + doctor doc now carries a derived `lifecycle` block in the closed vocabulary; emitted state verified equal to the-forge's own `receipt_state` re-derivation (see below) |
| Honest UNVERIFIED ≠ FAIL | DONE | `component:service` PATH probe stays `UNVERIFIED` (federated verdict `unverified`, lifecycle `applied`) — documented; observed `OSError` write errors now report `FAIL` → `status:"failed"` → lifecycle `failed` (previously blurred as UNVERIFIED) |
| Incremental reinstall (hash-compare) | DONE | `providers.json` preserved when detection unchanged; `pair.token`/`.gitignore`/`config.json` were already preserved; hash-compare test proves byte-identical preserved files; receipt names get a content-hash suffix (`install-<ts>-<id8>.json`) so same-second runs can't clobber evidence |
| MCP registration health | DONE | `mcp doctor` `config:*` checks now validate the *declared* entry (command/args/profile/env): `ready`/`unverified`/`error`; `mcp status` deduplicated (presence vs health documented) |
| Docs updated to real parser; examples run | DONE | README, CHANGELOG, `MCP_TROUBLESHOOTING.md`, `MCP_CORPORATE_INSTALLATION.md`; commands executed live (transcripts below) |
| Feature-freeze / no empty PR | OK | additive fields only; contract schemas unchanged; vendored API surface stable for product-forge resync |

## What changed (files)

- `src/forge_agent_bridge/install/lifecycle.py`
  - `LIFECYCLE_SCHEMA`, `LIFECYCLE_STATES`, `_lifecycle_block`,
    `_receipt_lifecycle` (mirrors the-forge `receipt_state`),
    `_doctor_lifecycle` (check-aware: no root → `unverified`; managed
    drift → `partially_applied`; unproven probes → `applied`; green →
    `ready`).
  - `OSError` during apply → check `FAIL` + `failed[]` bucket +
    `verification:"FAIL"` + `status:"failed"`.
  - `write-snapshot` preserves `providers.json` when `providers` array
    unchanged (compares content, not name); `detected_at` = "when this
    content was observed"; corrupt file → rewritten (repair).
  - receipt filename `install-<ts>-<id8>.json`; `_write_receipt` failure
    reported on the receipt (`receipt_persist`) instead of crashing.
  - doctor doc gains `lifecycle`.
- `src/forge_agent_bridge/mcp/diagnostics.py` — `_declared_entry_state`
  + `_config_check`; config errors drive `overall:"error"`.
- `src/forge_agent_bridge/mcp/cli.py` — `mcp status` dedupes target paths.
- `tests/test_install.py` — +8 wave-08 tests (lifecycle states,
  FAIL-vs-UNVERIFIED, hash-compare reinstall, receipt uniqueness).
- `tests/test_mcp_diagnostics.py` — new, 11 tests (declared-entry
  validation matrix).
- `README.md`, `CHANGELOG.md`, `docs/MCP_TROUBLESHOOTING.md`,
  `docs/MCP_CORPORATE_INSTALLATION.md` — docs §14.

## Verification evidence

### Gates

```
.venv/bin/python -m ruff check src tests            → All checks passed!
.venv/bin/python -m ruff check src/forge_agent_bridge/mcp tests/test_mcp_*.py
                                                    → All checks passed!
.venv/bin/python -m pytest -q                       → 228 passed in ~82s
```

### Federated verdict (the-forge `_delegation_verdict`, real call)

```
shim absent:   completed + UNVERIFIED → unverified/UNVERIFIED
               lifecycle: the-forge derived "applied" == emitted "applied"
write error:   failed    + FAIL       → failed/FAIL
               lifecycle: the-forge derived "failed"  == emitted "failed"
dry-run:       planned                → unverified/UNVERIFIED
               lifecycle: "planned" both ways
```

The earlier federated run's UNVERIFIED-when-shim-absent verdict is
**correct behavior** (state written, service verification pending —
"run the bootstrap installer", not "install broke"); it is now
documented in README + module docstring + CHANGELOG and expressed as
`lifecycle: applied`.

### Live CLI examples run

```
forge-bridge install --scope workspace --root /tmp/w08 --dry-run
  → forge/InstallReceipt/v1  status=planned  lifecycle.state=planned
forge-bridge install --scope workspace --root /tmp/w08 --host all \
    --profile recommended --gateway-profile economy --yes
  → completed + UNVERIFIED (no forge-bridge shim on PATH)  lifecycle=applied
  → managed: .forge-bridge/{.gitignore,pair.token,providers.json,components.json}
  → receipt: .forge-bridge/receipts/install-20261119T061316Z-50c4feca.json
forge-bridge install --scope workspace --root /tmp/w08 --yes   (2nd run)
  → skipped: state=exists, pairing=exists, providers=unchanged
  → second distinct receipt file — no clobber
forge-bridge install-status --root /tmp/w08
  → degraded + lifecycle.state=applied ("unproven probes: cli-on-path")
forge-bridge mcp configure --workspace /tmp/w08mcp --target workspace-portable
forge-bridge mcp doctor --workspace /tmp/w08mcp
  → overall=ready; config:workspace-portable=ready
    ("declared entry verified (command/args/profile)")
forge-bridge mcp status → deduped target list
```

## Notes / follow-ups (for the cycle, not this PR)

- `src/forge_agent_bridge` is vendored byte-parity inside product-forge's
  wheel → `product-forge scripts/check_bridge_parity.py` will flag drift
  until the wave-07 resync; all changes are additive/wrapper-safe
  (`bridge.install/uninstall/doctor` signatures unchanged; new keys only).
- `certified`/`blocked` are derived states the bridge can produce but has
  no operation emitting today (no internal approval gate; certification
  is a control-plane concept) — vocabulary supported, honestly unused.
- `status: "failed"` on write errors is *new*: federated verdicts now
  escalate real I/O failures to `failed` instead of `unverified` — the
  intended distinction per §5.3/§15.3.
