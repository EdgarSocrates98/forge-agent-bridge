# Changelog

## Unreleased — Cycle 16.1.1, Wave 07c (vendored fixes)

### Fixed
- `setup.sh`: python probe tolerates all-missing (`|| true`) — under
  `set -euo pipefail` it exited `rc=1` silently before
  `FORGE-PYTHON-NOT-FOUND` (vendored defect; canonical fix in
  the-forge wave-01). Regression: `tests/test_setup_scripts.py`.
- `ui/{kit,i18n,wizard}.py` re-vendored to canonical the-forge — all
  three had drifted (kit lacked the `installation` consolidated-plan
  block and lifecycle states); a repo-local parity test now covers the
  vendored copies (bridge sits outside `KIT_PARITY_REPOS`).

## Unreleased — Cycle 16.1, Wave 08 (InstallLifecycle/v1 + honest states)

### Added
- `forge/InstallLifecycle/v1` block on every receipt
  (install/apply/dry-run/uninstall) and on the `install-status`/doctor
  report — a *derived* state in the closed vocabulary
  (`planned`/`blocked`/`failed`/`applied`/`partially_applied`/`verified`/
  `unverified`/`ready`/`certified`), matching the derivation The Forge
  re-applies federated. Receipt `status` stays coarse (`planned`/
  `completed`/`failed`) — the lifecycle is the finer, honest position.
- `failed` bucket on apply receipts — observed write errors land there,
  distinct from `unverified` (absence of proof).
- `mcp doctor` now validates each *declared* `forgeAgentBridge` entry
  (§9.3 — "can this config actually start our server?"): `ready` when
  command/args/profile verify on this machine, `error` for structurally
  wrong entries (non-stdio type, bad profile, args that don't launch
  `forge_agent_bridge.mcp`, absolute command path that does not exist,
  unreadable file), `unverified` for the plausible-but-unprovable (bare
  command name off this PATH, `env.PYTHONPATH` absent here).

### Changed
- Observed write errors (`OSError`) during apply now report check
  `FAIL` → `verification: "FAIL"` → `status: "failed"` → lifecycle
  `failed`. Previously they were reported `UNVERIFIED`, which blurred
  *absence of proof* with *evidence of failure*. The shim-not-on-PATH
  case stays `UNVERIFIED` — the correct federated verdict.
- Incremental reinstall (§7.4): `providers.json` is preserved when the
  provider detection snapshot is unchanged — repeated installs no
  longer rewrite unchanged assets (hash-compare tested). Unchanged
  `pair.token`/`.gitignore`/`config.json` were already preserved.
- Persisted receipts are named `install-<ts>-<id8>.json` — a content-
  hash suffix prevents two installs in the same second from clobbering
  each other's evidence.
- A failure writing the persisted receipt file is reported on the
  receipt (`receipt_persist`) instead of crashing — the stdout receipt
  remains the evidence of record.

## Unreleased — Cycle 16, Wave 07 (install-2.1 delegation contract)

### Added
- `forge/InstallReceipt/v1` envelope on every lifecycle op — `operation`,
  `status`, `verification.status`, `managed_files`, `checks`, persisted
  under `<state>/receipts/` (delegated-install verification target).
- `forge-bridge pair` real HTTP flow: `/pair/exchange` (device session
  tokens), `--devices`, `--revoke`; unavailable states are named
  (`unavailable:no-pair-token`, `unavailable:bridge-not-running`).
- `forge-bridge serve --state-dir` / `FAB_STATE_DIR` — scoped state
  roots are actually servable, so `project`/`workspace` scopes are
  honest, not merely declared.
- Audit events `pair.exchange` and `pair.rotate` (device identity only —
  never token material).
- `--host` / `--gateway-profile` accepted as honest no-ops (recorded
  `requested_*` + `NOT_APPLICABLE` check) since the orchestrator always
  passes them.

### Changed
- `--root <dir>` is a target root: state lives under
  `<dir>/.forge-bridge`, never loose at the workspace/repository root.
- `POST /pair/rotate` no longer returns the new master token in the
  response body — it writes the 0600 `pair.token` and reports
  path/hash-preview only. `/pair/exchange` shape preserved.
- Uninstall is ledger-driven (`components.json` provenance): removes
  only install-recorded files, preserves and fully lists kept state
  (`pair.token`, `pairing.json`, `audit.jsonl`, `sessions.json`,
  `secrets.json`, `provider-work/`, `events/`, `backups/`, pre-existing
  `config.json`); legacy ledgers fall back to always-generated artifacts
  only.
- Receipts never embed token material — path and hash-prefix only.
- Doctor accepts provider counts `0/5..5/5` (stale `/4` removed).
- `forge.json` (root + package): `installation_kind: "service"`,
  `depends_on: []`, `mcp_server_name`, `mcp_verify_tool: "forge_health"`,
  full `install` block (ops `plan/apply/status/doctor/uninstall`,
  scopes, profiles, flags incl. `--yes` approval).

### Security
- Master pair token confined to `<state>/pair.token` (0600): absent from
  stdout, receipts, logs and audit records.
- HTTP rotation response carries no credential material.

## 0.2.4
- Re-vendored installkit 1.2.0 + `forge_bootstrap` (canonical install-2.1
  fields); `mcp_verify_tool` declaration; packaged `resources[]` in the
  agentic manifest.
