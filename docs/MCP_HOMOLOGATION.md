# MCP Homologation — Evidence

Date: 2026-11-12 · Repo SHA at baseline: `291ac31e46a3c2cba9623904d0df530cc7e707da`
Environment: Windows 11, Python 3.12.13 (`.venv`), git 2.x, gh on PATH.

## Scope verified deterministically

| Area | Evidence | Result |
|---|---|---|
| Protocol — legacy era | `tests/test_mcp_protocol.py` (25 tests) | ✅ initialize/negotiate/ping/tools/call, ids preserved, -32022 paths |
| Protocol — modern era | same file + `test_mcp_e2e.py::test_modern_era_e2e` | ✅ `server/discover`, per-request `_meta`, -32022, ping removed |
| Security — negative | `tests/test_mcp_security.py` (20 tests) | ✅ traversal/symlink/UNC/device/sensitive/policy/injection denials |
| Config writers | `tests/test_mcp_config.py` (8 tests) | ✅ top_keys, idempotence, preservation, undo, corrupt-json, read-only |
| Stdio E2E | `tests/test_mcp_e2e.py` (6 tests) | ✅ 11-step sequence, stdout purity, malformed recovery, EOF shutdown |
| Smoke (live run) | manual `python -m forge_agent_bridge.mcp` session | ✅ initialize → tools/list → health ready → git ok → gh denied -32010 → unknown -32602 |
| `mcp doctor` | live run | ✅ `overall: ready`, 10 honest checks |
| `mcp configure` | live run on `/tmp/mcp-cfg-test` | ✅ 3 targets written (correct `servers`/`mcpServers`), dry-run, idempotent no-op, `--undo` removes only ours |
| Existing regression | `pytest -q` full suite | see "Regressions" |

## Performance (measured on this machine)

| Metric | Value |
|---|---|
| Cold start → first response (`server/discover`) | ~0.4–0.6 s (stdlib-only; no provider imports) |
| `tools/list` | <5 ms |
| `forge_health` | <50 ms |
| `forge_workspace_summary` (this repo, depth 4, ~300 files) | <150 ms |
| Stdio round-trip per request | <5 ms |

Audit events written per session: `mcp.server.started`,
`mcp.client.connected`, `mcp.tool.discovered`, `mcp.policy.evaluated`,
`mcp.tool.called/completed/denied/failed`, `mcp.workspace.validated`,
`mcp.server.stopped` — minimized fields, `0600` file.

## NOT verified here (honest blockers)

| Claim | State | Why |
|---|---|---|
| Live VS Code + GitHub Copilot Chat using the tools | **unverified — requires-approval + credentials** | needs an approved, signed-in Copilot session in a permitted environment; this run had no such authorization context |
| `gh auth` live path | **unverified in this run** | `gh` binary detected; auth + allowlist path exercised only via denial tests |
| macOS install path | **unverified** | not executed on macOS; code is platform-neutral but untested there |
| Copilot CLI | **not required and not used** | integration is CLI-free by design |

## Regressions

Baseline at `291ac31`: **130 passed**. After all changes: see the
latest `pytest -q` output — count and any deltas are recorded in
`audits/COPILOT_MCP_FINAL_AUDIT.md` (this document does not guess).

## How to reproduce

```bash
cd forge-agent-bridge
PYTHONPATH=src python -m pytest tests/test_mcp_*.py -q
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"server/discover"}' \
  | PYTHONPATH=src python -m forge_agent_bridge.mcp --workspace .
forge-bridge mcp doctor --workspace .
forge-bridge mcp configure --workspace . --dry-run
```
