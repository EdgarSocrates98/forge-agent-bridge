# ADR-001 — forge-agent-bridge: independent repository (Option B)

**Status**: Accepted · **Date**: 2026-10-30

## Decision

The Forge Agent Bridge ships as its own distribution
(`forge-agent-bridge`), per §4.2 Option B.

## Criteria weighed

| Criterion | Assessment |
|---|---|
| Cohesion | Bridge concerns (sessions, events, approvals, providers) are orthogonal to Product Forge's product-intelligence domain |
| Coupling | PF must depend on **public interfaces** — a private package inside PF would make the bridge de-facto implementation detail |
| Release independence | Provider adapters (Claude/Codex/Devin) will rev on vendor CLIs, not on PF releases |
| Security boundary | Bridge spawns agent processes and brokers approvals — a distinct trust surface that deserves its own threat model |
| Consumer compatibility | Forge Portal, PF, and future forges all consume the same contracts; a shared dist avoids drift |

## Boundaries

- Portal owns experience; Bridge owns connection; agent runtime executes;
  policies authorize; Product Forge supplies knowledge/tools.
- Contracts are `forge/AgentBridgeEvent/v1` + typed entities; capability
  honesty is enforced (`unverified`/`requires-*` states, never simulated).
