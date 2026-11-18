# Changelog

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
