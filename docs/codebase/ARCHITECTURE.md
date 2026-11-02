# Architecture

## Core Sections (Required)

### 1) Architectural Style

- Primary style: provider-adapter architecture around a local HTTP session broker.
- Why: `BridgeOrchestrator` coordinates a common lifecycle while provider modules translate Claude stream-json, Codex JSONL/resume and Devin ACP; fake is used for deterministic tests.
- Primary constraints: local-only binding, bearer pairing, honest capability states and provider-specific recovery semantics.

### 2) System Flow

```text
HTTP/CLI request -> local_bridge auth/router -> orchestrator -> provider adapter/process -> events/audit -> HTTP replay/stream response
```

1. The user installs and pairs the bridge.
2. A client calls the local HTTP surface with the bearer token.
3. The orchestrator creates a session and selects a registered provider runner.
4. The adapter drains provider output into typed events and stores replayable state.
5. Cancellation, approval, handoff and close produce explicit lifecycle/audit events.

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|-------------|----------|
| contracts/events | stable wire vocabulary | provider process parsing | `contracts.py`, `events.py` |
| orchestrator | lifecycle, budgets, collaboration | browser/UI state | `orchestrator.py`, `budgets.py` |
| providers | provider spawn/stream/resume | common API envelopes | `providers/` |
| local bridge | transport, pairing, origin policy | Product Forge domain data | `local_bridge.py`, `pairing.py` |
| install | isolated runtime and doctor | application session lifecycle | `install/`, `scripts/forge_bootstrap.py` |

### 4) Reused Patterns

| Pattern | Where found | Why it exists |
|---------|-------------|---------------|
| Adapter | `providers/` | normalize heterogeneous agent CLIs/protocols |
| Registry | `registry.py`, runner registry | discover capabilities and providers |
| Replayable event stream | `events.py`, local bridge | reconnect/resume and auditability |

### 5) Known Architectural Risks

- The bridge is independently installable and independently started, so Product Forge must currently know how to discover/authenticate it.
- Provider capability truth is necessarily dynamic; callers must not assume “installed” means “ready”.
- Process supervision and restart ownership across Product Forge and Bridge is not a single documented contract.

### 6) Evidence

- `README.md`
- `src/forge_agent_bridge/orchestrator.py`
- `src/forge_agent_bridge/local_bridge.py`
- `src/forge_agent_bridge/providers/`
