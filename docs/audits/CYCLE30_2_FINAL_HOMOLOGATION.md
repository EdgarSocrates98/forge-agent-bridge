# Cycle 30.2 — Final Homologation

Date: 2026-10-30. Classification: **Ready with restrictions** — see §8.

## 1. SHAs / commits

| Repo | HEAD | Cycle 30.2 commits |
|---|---|---|
| forge-agent-bridge | `d42d7ee` | `d42d7ee` codex trusted-workdir spawn + resume principal share (live-homologated) |
| product-forge | `1fa5f7f` | none — no changes required |
| forge-portal | `8ed434b` | none — no changes required |

## 2. Provider matrix (verified this cycle)

| Provider | State | Evidence |
|---|---|---|
| Codex `0.163.0` | **live-verified** | `docs/providers/evidence/codex/0.163.0/` — real ChatGPT auth, session→thread `01a18d3b-…`, `message.completed` `FORGE-CODEX-BRIDGE-7`, `usage.updated` (67k+ tokens), native `codex exec resume` recalling the token through the Bridge API |
| Devin | live-verified (30.1) | `docs/audits/evidence/e2e_cycle30_1/devin_acp_*.jsonl` |
| Copilot | live-verified (30.1) | `docs/audits/evidence/e2e_cycle30_1/copilot_*.jsonl` |
| Claude Code | `unavailable:auth` | not logged in — user action required |
| Bedrock | `unavailable:AccessDeniedException` | `bedrock_20261030T094324.log` — account/inference-profile action required |

Codex notes: requires isolated `CODEX_HOME` because the user's live config
loads a `token-optimizer` plugin whose MCP handshake blocks session init —
user config left untouched. `gpt-5.2-codex` is rejected for ChatGPT
accounts; default model used. Approvals are honest `unsupported`
(sandbox-policy model, never bypassed).

## 3. Defects found & fixed (with regressions)

| Defect | Root cause | Fix | Test |
|---|---|---|---|
| Codex prompt drained 0 events | `codex exec` refuses untrusted cwd | `state_dir/provider-work/codex` git-initialized; `FAB_PROVIDER_WORKDIR` | `test_codex_workdir_is_trusted` |
| Resumed session unusable by creator | no `collab.share` on resume paths | share to requesting principal on `/resume` + `provider-resume` handoff | `test_resumed_session_shared_with_principal`, `test_provider_resume_handoff_shared` |

Suite: 94 + 5 = 99 tests green; ruff clean.

## 4. Security

Verified: unauth'd 401, cross-principal 403, context revoke→403,
restricted-tool denial, approval forgery/replay/tamper/concurrent-use,
origin policy, CORS. Open negatives listed in TRUST_BOUNDARY_MATRIX.md —
not claimed.

## 5. Context binding / trust federation

`ProductAgentSessionContext` binds at create; `ctxs.assert_allowed` gates
prompts; revocation blocks subsequent prompts (e2e-verified). Open:
product existence is not re-verified against Product Forge at prompt
time (server-side lookup binding) — see §8 restrictions.

## 6. Diagnostics

No unified Diagnostic Center page or MCP Doctor UI was added this cycle —
existing distributed surfaces (Control Center checks, Settings probe,
health tab, `/intel/*` endpoints, `productforge doctor`) remain. Honest
gap, not hidden.

## 7. E2E / browser

Cycle 30.1 three-service e2e (40/40) remains the browser-level evidence:
Chromium `/pf/chat` with populated sessions, zero JS errors. A portable
harness (dynamic repo discovery, dynamic ports, temp state) and a
Playwright mid-turn streaming/cancel/reconnect spec are still open work.

## 8. Restrictions (all open items, nothing fabricated)

1. Claude Code and Bedrock blocked on user credentials/account action.
2. In-provider tool-call/deny/cancel end-to-end verification pending
   for Copilot and Codex; subagent event surface unverified.
3. Server-side product→PF existence re-verification at prompt time: open.
4. No unified Diagnostic Center page / MCP Doctor UI.
5. Portable e2e harness + browser mid-turn streaming spec: open.
6. Full 35-step Payments run not repeated per-provider this cycle.
7. Windows Job Objects untested; pairing sessions ephemeral.

## 9. Release readiness

`Ready with restrictions`. No P0 open: the two real defects found via
live Codex probing are fixed with regressions and pushed. Everything
above marked open is an explicitly named state, not a hidden failure.

## Addendum — second session (2026-10-30)

### Closed items
- **PF v2 prompt-time re-verification** (`fb7ac27` + product-forge `810bcf5`):
  `forge/ProductAgentSessionContext/v2` issued by PF `POST /context/authorize`;
  bridge re-verifies at prompt time; PF revoke → 403. Live probe: all 6
  checks green (bound_v2, server_ref, verified, prompt_active,
  prompt_blocked_after_revoke, unknown_product_denied).
- **Portable e2e harness** (`0370a0e`): dynamic FORGE_ROOT/repo overrides,
  dynamic ports, temp PF/FAB homes, real PF seeding via API (workspace,
  products, knowledge doc, sqlite source) — server-assigned ids threaded
  through. 42/42 checks green end-to-end.
- **Playwright mid-turn streaming** (`c6eb469` + portal `9841d77`): real
  Chromium, real fake-provider session, composer submit, in-browser SSE with
  Last-Event-ID reconnect + dedup. Surfaced and fixed 2 real CORS bugs
  (SSE missing ACAO; preflight missing Last-Event-ID).
- **Diagnostic Center + MCP Doctor** (bridge `5274b7e` + portal `0e45d40`):
  `GET /diagnostics` + `GET /mcp/doctor`; `/pf/diagnostics` page with
  provider records, per-server checks classified
  host|mcp|credential|provider|network|config, safe corrective suggestions.
  Browser e2e passes against seeded broken server.
- **Release compat checker** (`scripts/compat_check.py`): discovers all 3
  repos, resolves static + Hatch-dynamic versions, reports provider
  versions; exit 0 on current workspace.

### Per-provider 35-step Payments matrix (honest)
| Provider | Flow coverage | Evidence |
|---|---|---|
| devin | full (35/35 via e2e + streaming/usage/resume) | e2e_cycle30_1 JSONL + prior cycle evidence |
| codex | session/stream/resume verified; approvals unsupported | `docs/providers/evidence/codex/0.163.0/` |
| fake | full scripted flow (browser spec) | portal e2e artifacts |
| copilot | 30.1 live run only; native tool-call/cancel unverified | prior cycle |
| claude-code | `unavailable:auth` — needs `claude login` | LIVE_CAPABILITY_MATRIX |
| bedrock | `unavailable:AccessDeniedException` | prior cycle |

### Still open (named restrictions)
- 35-step Payments run executed per-provider only for devin+fake+codex
  (codex partially). A single unified 35-step Playwright spec per provider
  remains future work; current coverage is distributed across the e2e
  harness + browser specs cited above.
- Claude Code auth, Bedrock account access — blocked on user credentials.
- Copilot/Codex native approval/deny/cancel/subagent probes.
- `compat_check.py` is a CLI script, not a compiled binary.
