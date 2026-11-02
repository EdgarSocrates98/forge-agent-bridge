# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|----------|---------|----------|--------|------------------|
| high | independent install/process/token lifecycle | `README.md`, `install.sh`, `forge.json` | user must assemble runtime manually | let Product Forge compose and supervise Bridge |
| high | provider readiness is dynamic and heterogeneous | `README.md`, `CAPABILITY_MATRIX.md` | UI can promise a provider that cannot run | expose capability state directly in one workspace |
| high | cross-repo compatibility is evidence-heavy but not one command | `docs/audits/CROSS_REPO_COMPATIBILITY.md` | integration regressions are expensive to diagnose | one system harness invoked by `productforge install --verify` |
| medium | high churn in `local_bridge.py` and contracts | scan git churn | transport/auth regressions | additive versioned contracts and consumer tests |

### 2) Technical Debt

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|-----------|---------------|-------|-----------------|---------------|
| duplicated installation entry points | standalone bridge and Product Forge parity | `install*.sh`, `install/`, `forge.json` | conflicting environments | one delegated installer API |
| provider-specific semantics leak upward | adapters differ in resume/approval | `providers/`, contracts | complex UI branching | normalize state machine and capability metadata |

### 3) Security Concerns

| Risk | OWASP category | Evidence | Current mitigation | Gap |
|------|-----------------|----------|--------------------|-----|
| local bearer token misuse | A07 | `pairing.py`, `docs/SECURITY.md` | loopback and permissions | central rotation/ownership |
| subprocess/workdir trust boundary | A03 | `providers/codex.py`, security docs | trusted workdir checks | cross-repo policy must be identical |
| provider output in audit artifacts | A09 | `docs/audits/evidence/` | audit/redaction design | prove no secrets in system-level receipts |

### 4) Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---------|----------|-----------------|-------------|-----------------------|
| event replay and buffering | `events.py`, perf smoke tests | 5k-event replay is explicitly tested | memory growth on long sessions | bounded retention and UI pagination |
| one local process per bridge | `local_bridge.py` | simple local model | restart/port collisions | supervisor-owned lifecycle |

### 5) Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|------|-------------|--------------|----------------------|
| `local_bridge.py` | auth, SSE, diagnostics and routing | 17 recent commits per scan | contract tests + no breaking route changes |
| `providers/codex.py` | resume/trusted workdir semantics | recent live fixes | preserve provider evidence matrix |

### 6) `[ASK USER]` Questions

1. [ASK USER] Should Bridge remain usable standalone after Product Forge takes ownership of its lifecycle?
2. [ASK USER] What provider failure should the non-technical UI explain first: missing CLI, missing auth, quota, or unsupported capability?

### 7) Evidence

- `docs/codebase/.codebase-scan.txt`
- `README.md`, `forge.json`, `install.sh`
- `src/forge_agent_bridge/local_bridge.py`, `contracts.py`, `providers/`
