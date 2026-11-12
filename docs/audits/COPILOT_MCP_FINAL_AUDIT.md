# Copilot MCP — Final Audit

Date: 2026-11-12 · Baseline SHA `291ac31e46a3c2cba9623904d0df530cc7e707da`
· Package 0.2.2.

## Executive summary

The Forge Agent Bridge gained a **native, stdlib-only MCP stdio server**
serving 7 read-only tools under a fail-closed workspace trust boundary,
three security profiles, dual-era protocol support (legacy `≤2025-11-25`
handshake + modern `2026-07-28` stateless), host config writers for
Copilot/VS Code, honest diagnostics, minimized audit, and a CI workflow.
Ten pre-existing security findings (2 P0) were fixed along the way.
Suite: **190 tests passing** (130 baseline → +60), ruff clean.

## Cycles delivered

| Cycle | Scope | State |
|---|---|---|
| 0 — hardening | copilot `--allow-all-tools` removed; MCP-auth-before-spawn; nonce opt-in; cwd validation; session-id consistency; scrub_env; scope clamp; trust force; 0600 writers; typed HTTP errors | ✅ |
| 1 — server | `mcp/` package: protocol/dispatcher/stdio/registry/security/workspace/audit, 3 profiles, dual-era | ✅ |
| 2 — tools | 7 read-only tools, honest states, untrusted-content marking | ✅ |
| 3 — profiles | corporate-readonly/local-readonly/standard, fail-closed | ✅ |
| 4 — CLI/config | `mcp serve\|configure\|doctor\|status\|tools`; mcpServers/servers writers; dry-run/idempotent/undo | ✅ |
| 5 — tests | 60 new: protocol, security-negative, injection, E2E, config | ✅ |
| audit/doctor | `mcp.*` events + `mcp doctor` honest checks | ✅ |
| docs | 9 MCP docs + 3 audits + README + CAPABILITY_MATRIX | ✅ |
| CI | `.github/workflows/mcp.yml`: matrix (2 OS × 3 Python), e2e, packaging, offline launch, manifest | ✅ |

## Security matrix (proof)

| Control | Evidence |
|---|---|
| Path traversal denied | `test_traversal_dotdot_denied`, `nested`, `absolute`, `unc`, `device` |
| Symlink escape denied | `test_symlink_escape_denied` (posix) |
| Sensitive files unreadable | `test_sensitive_files_denied`, scan-exclusion test |
| Denied-before-validated | `test_call_denied_before_arg_validation` (-32010 wins) |
| gh tool gated | profile default-deny + `denied:no-authorized-repos` + `repo-not-authorized` |
| Injection is data | `untrusted_content` + `test_injection_in_args_is_data` |
| No exec tool exists | static catalog — 7 read-only only |
| Audit minimized | `test_audit_minimized_no_content`, no content fields |
| stdout purity | `test_stdout_purity`, malformed-line recovery |
| Clean shutdown | EOF→rc 0, SIGTERM handler, `test_full_sequence` step 11 |

## Compatibility classification

| Capability | Class | Evidence |
|---|---|---|
| MCP server + tools | `ready` (deterministically tested) | 58 tests + live stdio |
| Legacy `≤2025-11-25` | `ready` | initialize/ping/negotiate tests |
| Modern `2026-07-28` | `ready` | discover/meta-version/-32022 tests |
| Config writers | `ready` | idempotence/preservation/undo tests + live run |
| `mcp doctor` | `ready` | live run `overall: ready` |
| Live Copilot Chat tool use | **`unverified — requires-approval`** | needs authorized Copilot session |
| `gh` live auth path | `unverified` | binary present; auth path only denial-tested |
| macOS | `unverified` | platform-neutral code, not exercised there |

## Test counts

| Suite | Count | Note |
|---|---|---|
| `tests/test_mcp_protocol.py` | 25 | dual-era, framing, errors, ids |
| `tests/test_mcp_security.py` | 20 | negative + injection + audit |
| `tests/test_mcp_config.py` | 8 | writers |
| `tests/test_mcp_e2e.py` | 6 | subprocess, purity, shutdown |
| pre-existing suite | 130 | +1 manifest-copy fix → **190 total** |

## Pending (honest)

- **Live VS Code + Copilot homologation** — blocked on an authorized,
  signed-in Copilot session in a permitted environment; not simulated.
- **HTTP nonce default-strict** — `FAB_REQUIRE_NONCE` is opt-in by wire
  compatibility; corporate deployments should enable it.
- Windows TOCTOU residual (documented, narrowed).
- Codex session-id hint propagation — verify parity across adapters on
  next provider cycle.

## Verdict

`ready` for deterministic use (all non-credential paths verified);
`unverified — requires-approval` for the live Copilot surface, by
honest classification rather than simulation.
