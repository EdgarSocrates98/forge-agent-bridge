# External Integrations

## Core Sections (Required)

### 1) Integration Inventory

| System | Type (API/DB/Queue/etc) | Purpose | Auth model | Criticality | Evidence |
|--------|---------------------------|---------|------------|-------------|----------|
| Claude Code | local subprocess/stream | agent session execution | provider CLI auth | high | `providers/claude.py`, `README.md` |
| Codex CLI | local subprocess/JSONL | agent session execution/resume | provider CLI auth | high | `providers/codex.py`, `README.md` |
| Devin ACP | ACP/HTTP session | agent session execution | ACP/provider auth | high | `providers/acp_adapter.py`, `docs/DEVIN_INTEGRATION.md` |
| Product Forge | local HTTP client | product workspace orchestration | bearer/paired local bridge | high | `docs/audits/CROSS_REPO_COMPATIBILITY.md` |
| Filesystem | local state | pairing, backups, artifacts and audit | permissions | high | `pairing.py`, `backup.py`, docs |

### 2) Data Stores

| Store | Role | Access layer | Key risk | Evidence |
|-------|------|--------------|----------|----------|
| local files | sessions, replay, pairing, backup | bridge modules | permissions/lifecycle | `src/forge_agent_bridge/` |
| provider process streams | transient events | adapters/orchestrator | ordering/backpressure | `events.py`, providers |

### 3) Secrets and Credentials Handling

- Credential sources: local pairing token and provider CLI/environment auth.
- Hardcoding checks: no `.env.example`; full scan result is `[TODO]`.
- Rotation/lifecycle: pairing persistence and local permissions are covered by tests/docs; unified rotation with Product Forge is `[TODO]`.

### 4) Reliability and Failure Behavior

- Session lifecycle supports replay, cancellation and handoff/recovery.
- Remote placement is refused until health probing succeeds.
- Retry/timeout policy is adapter-specific; cross-component retry ownership is `[TODO]`.

### 5) Observability for Integrations

- Diagnostics, audit events and homologation evidence are present.
- Missing: one correlation ID and one health document spanning Portal → Product Forge → Bridge.

### 6) Evidence

- `README.md`
- `src/forge_agent_bridge/contracts.py`
- `src/forge_agent_bridge/pairing.py`
- `docs/audits/CROSS_REPO_COMPATIBILITY.md`
