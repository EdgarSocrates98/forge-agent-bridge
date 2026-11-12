# Copilot MCP — Baseline Audit

Recorded at task start · SHA `291ac31e46a3c2cba9623904d0df530cc7e707da`
· Version 0.2.2 · Python ≥3.11 · `pytest -q` = **130 passed**.

## What existed

| Asset | State |
|---|---|
| HTTP bridge (`forge-bridge serve`) | sessions/runners/budgets/shares/audit on 127.0.0.1, pairing token |
| Provider adapters | claude, codex, devin(ACP), copilot, fake + bedrock inventory |
| Copilot provider adapter | `providers/copilot.py` — `copilot -p <prompt> --silent` |
| `forge.agentic.json` | declared `mcp_command: ["{cli}", "serve"]` — **wrong**: `serve` is HTTP, not MCP stdio |
| MCP surface | **none** — no native server; `mcp_servers` only passed through to providers |
| Docs | API/CAPABILITY_MATRIX/SECURITY/THREAT_MODEL/HOMOLOGATION — no MCP docs |

## Findings (severity)

| # | Sev | Finding | Fix |
|---|---|---|---|
| F1 | **P0** | `providers/copilot.py` invoked `copilot -p … --allow-all-tools` — blanket tool authorization on every prompt | removed; opt-in `FAB_COPILOT_ALLOWED_TOOLS` with strict named-pattern validation; unrestricted patterns (`all`,`*`,`tools`,`shell(*)`,`(*)`) refused via typed `SessionError` |
| F2 | **P0** | `POST /agent-sessions` passed raw `mcp_servers` to provider spawn *before* `mcp_fed.allowed_for` filtering — denied servers reached providers | session-id pre-generated → MCP servers authorized → **only approved list** passed to `create_session`; denied ids returned honestly; meta cleaned up on failure |
| F3 | High | Nonce (`X-FAB-Nonce`) optional on all requests — replay window unenforced by default | `FAB_REQUIRE_NONCE=1` requires nonces on POST/PATCH/DELETE (except `/pair/exchange` bootstrap); opt-in preserves wire contract |
| F4 | High | `POST /sessions` accepted arbitrary `cwd` — non-directory paths reached supervisor | typed `FAB-VALIDATION` denial before spawn |
| F5 | Medium | Provider session ids re-generated inside adapters → bridge meta/context/audit ids diverged | `session_id` hint accepted by all adapters; bridge id is the canonical id |
| F6 | Medium | Env inherited by spawned providers could carry secrets | `scrub_env()` on ACP + Codex subprocess launches |
| F7 | Medium | `pair/exchange` auto-elevated caller-declared scopes | scopes clamped to broker vocabulary |
| F8 | Medium | `POST /mcp` honored self-declared `trust` | trust forced by server |
| F9 | Low | `context.py` writers left world-readable files | `0600` via `_chmod_private` |
| F10 | Low | generic 4xx envelope collapsed all FAB errors | `_err_status` maps typed errors → honest statuses (401/403/404/409/422/429/502), preserving `FAB-UNAVAILABLE→502` contract |

## Consumers analyzed

product-forge (workspace/product contexts), forge-portal (Chat Studio
session surface), the-forge (installkit + contracts) — no contract
break; the MCP surface is additive.

## Baseline verdict

Bridge was a solid session layer but had **no MCP surface at all** and
two P0 authorization-ordering defects. `forge.agentic.json` advertised
an MCP command that pointed at the wrong transport.
