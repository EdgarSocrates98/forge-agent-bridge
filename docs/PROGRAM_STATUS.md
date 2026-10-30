# Program Status — prompt_evo_pf_continuos.md

| Cycle | Items delivered | Evidence |
|---|---|---|
| 25 — security | typed ops, pair/session tokens, broker authz, approval tokens, SSRF, secrets, threat model, CI+SBOM, risk-tiered PF gates | `5b3e190`, `a20b494`, `a8f092b`, PF `785b717`, Portal `27e57a4` |
| 26 — providers/streaming | versioned capability matrix (`forge/ProviderCapabilityMatrix/1`, 14 caps, honest states); SSE `/agent-sessions/{id}/stream` (cursor/dedup/heartbeat/reconnect); Portal fetch-SSE client (poll=fallback) | `dbeb5fa`, Portal `b3928ee`, `test_cycle26` |
| 27 — context federation | `forge/ProductAgentSessionContext/v1` bind at create, expiry gate, context attach/draft, `forge/MCPServerDescriptor/v1` federation + allowlist (`mcp_denied`), `forge/AgentContextDelta/v1` capture | `2c98fa9`, `test_cycle27` |
| 28 — durability | `DurableEventStore` JSONL (0600) — seq/id/ts/redaction/cursor/retention-marker; restart-safe `seq_floor`; `forge/SessionRecoveryPlan/v1`; POSIX process-group + Windows process-tree termination; `backup.py` (secrets excluded by construction) + `/backup` + approval-gated `/backup/restore` | `6755eb0`, `60e8d04`, `test_cycle28`, `test_cycle29` |
| 29 — UX | Portal: Agent Control Center, Session Compare, Forge Lens, Artifact Studio, Workflow Builder (design-time `forge/AgentWorkflow/v1`), Agent Templates, Product Intelligence Actions, degraded-mode banner, a11y (scope'd `<th>`, aria labels) | Portal `3dd21e6`, 579/579 specs |
| 30 — release | Contract tests (schema/envelope/seq invariants for every public surface), full-lifecycle HTTP E2E (session→prompt→SSE→cancel→delete→backup), release gate script | `test_cycle30`, `scripts/release_gate.sh` |
| Part IX | `/intel/*` deterministic endpoints: provider routing (capability-scored `forge/ProviderRouting/v1`), session quality axes, context health, replay dossier (read-only), decision records, FinOps rollup (token counts real; USD only when provider-reported), degraded mode, workspace intelligence | `intelligence.py`, Portal `/pf/intelligence` + `/pf/lens` |

## Honest gaps (not claimed)

- **26.2–26.5**: provider live-homologation pending credentials — Claude Code / Codex / Devin adapters detected and classified, but `session-resume`/`subagents`/`plans`/`usage` remain `unverified` until exercised against live provider sessions. Browser E2E is contract-simulated (fake provider), not live.
- **28.4**: Windows Job Objects are implemented via `taskkill /T /F` process-tree termination only; Job Object grouping remains **unverified** (no Windows CI host).
- **28.7**: perf runs at 20–100 concurrent sessions not executed — no load harness exists; durable store is functional-verified only.
- **Part IX partial**: agent marketplace, A2A handoff package format, and replay *re-execution* (sandbox+consent) are documented-not-built — `forge/ReplayDossier/v1` is explicitly `replay_mode: read-only`.
- **Payments scenario** (§30 acceptance): requires live Product Forge + Bridge + Portal + provider credentials in one environment — not executed here.
