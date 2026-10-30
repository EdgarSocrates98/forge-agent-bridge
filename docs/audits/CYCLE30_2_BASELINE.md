# Cycle 30.2 — Baseline

Recorded at cycle start (2026-10-30). All three `main` branches pulled;
all were already at the Cycle 30.1 reference SHAs.

## Repository state

| Repo | SHA at baseline | CI at baseline | vs Cycle 30.1 ref |
|---|---|---|---|
| forge-agent-bridge | `724e7e3` | ✅ green (core + security) | unchanged |
| product-forge | `1fa5f7f` | ✅ green | unchanged |
| forge-portal | `8ed434b` | ✅ green (incl. Chromium e2e) | unchanged |

No open PRs or issues affecting the cycle were found on any repo.

## Provider state at baseline

| Provider | State at baseline | Evidence |
|---|---|---|
| Devin | `live-verified` (Cycle 30.1) | `docs/audits/evidence/e2e_cycle30_1/devin_acp_*.jsonl` |
| Copilot | `live-verified` (Cycle 30.1) | `docs/audits/evidence/e2e_cycle30_1/copilot_*.jsonl` |
| Codex | `unavailable:mcp-config` → **resolved** this cycle | see below |
| Claude Code | `unavailable:auth` (not logged in) | probe 2026-10-30 |
| Bedrock | `unavailable:AccessDeniedException` | `bedrock_20261030T094324.log` |

## Codex baseline investigation

- `/home/edgar/.codex/config.toml` loads plugins incl. `token-optimizer`,
  whose MCP handshake fails and blocks `codex exec` session init.
- **User config was not modified.** An isolated `CODEX_HOME=/tmp/codex_hom`
  (minimal config + copied auth) was used for homologation instead.
- Isolated direct CLI verification: real ChatGPT auth, real thread,
  JSONL event stream (`thread.started`, `turn.started`, `item.completed`,
  `agent_message`, `turn.completed`), real usage, `codex exec resume`
  recalling prior context.
- `gpt-5.2-codex` is rejected by ChatGPT-account Codex
  (`model_not_found`); default model works.

## Bridge defects found at baseline (via Codex probe)

1. `codex exec` spawned from an untrusted cwd → zero drained events.
2. `/agent-sessions/{sid}/resume` + `provider-resume` handoff created
   sessions with no `collab.share` → creator got `FAB-FORBIDDEN`.

Both fixed in `d42d7ee` with regression tests (`tests/test_cycle30_2.py`).

## Carried-over Cycle 30.1 restrictions (input to this cycle)

- In-provider tool-call/approval/deny/cancel flows unverified.
- No unified Diagnostic Center page; diagnostics are distributed.
- No version compatibility checker.
- Pairing sessions ephemeral; Windows Job Objects untested.
- Server-side `product_id` lookup binding unverified.
