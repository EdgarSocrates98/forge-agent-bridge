# Codebase Structure

## Core Sections (Required)

### 1) Top-Level Map

| Path | Purpose | Evidence |
|------|---------|----------|
| `src/forge_agent_bridge/` | contracts, orchestration, providers, HTTP bridge, install | scan tree |
| `src/forge_agent_bridge/providers/` | Claude/Codex/Devin/fake adapters | scan tree; `README.md` |
| `tests/` | contract, cycle, install and performance tests | scan tree |
| `scripts/` | bootstrap, compatibility and E2E harnesses | scan tree |
| `docs/audits/` | live homologation and trust evidence | scan tree |

### 2) Entry Points

- Main CLI: `forge_agent_bridge.cli:main`, exposed as `forge-bridge`.
- Install entry: `forge-bridge install` and checkout-independent shell/PowerShell scripts.
- Runtime entry: local bridge server in `src/forge_agent_bridge/local_bridge.py`.

### 3) Module Boundaries

| Boundary | What belongs here | What must not be here |
|----------|-------------------|------------------------|
| contracts | typed public wire models | provider subprocess details |
| orchestrator | create/prompt/drain/replay/cancel/close lifecycle | UI rendering |
| providers | provider-specific process/ACP adaptation | cross-provider policy duplication |
| local_bridge | HTTP/auth/transport | domain product persistence |
| install | bootstrap, registry, smoke, doctor | chat execution |

### 4) Naming and Organization Rules

- Python modules and tests use `snake_case`; provider adapters are named by provider.
- Responsibilities are grouped by runtime concern and provider boundary.
- `forge.json` is the machine-readable distribution/install contract.

### 5) Evidence

- `pyproject.toml`
- `forge.json`
- `src/forge_agent_bridge/local_bridge.py`
- `src/forge_agent_bridge/orchestrator.py`
