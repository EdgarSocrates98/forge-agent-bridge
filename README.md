# Forge Agent Bridge

A **provider-agnostic agent session bridge** for the Forge ecosystem. One
local HTTP surface exposes Claude Code, Codex CLI and Devin sessions through a
single typed contract — so Forge Portal's Chat Studio (or any host) can create,
prompt, approve, replay and hand off agent sessions without knowing provider
CLI details.

Part of the [Product Forge](https://github.com/EdgarSocrates98/product-forge)
ecosystem. Architectural decision: [docs/adr/ADR-001-repo-and-architecture.md](docs/adr/ADR-001-repo-and-architecture.md).

## What it does

| Capability | How |
|---|---|
| **Session orchestration** | `BridgeOrchestrator` — create → prompt → drain → replay → cancel → close per provider adapter |
| **Real provider adapters** | Claude (`stream-json` bidirectional), Codex (`exec --json` JSONL + resume), Devin (`acp` native), `fake` for tests |
| **Local bridge service** | stdlib HTTP on `127.0.0.1` only, pairing bearer token (`0600`), process supervisor |
| **Runner registry** | local + remote runners; remote starts `unverified`, health probe gates placement |
| **Budgets** | scoped limits (user/workspace/product/provider/session), day/month windows, real token recording |
| **Collaboration** | owner/observer/delegated-approver roles, visibility, comments — observers are read-only |
| **Audit** | append-only trail for session/runner/share/budget/approval/handoff actions |
| **Handoff** | `remote` / `provider-resume` / `context-rebuild` — never claims unverifiable continuity |
| **File service** | path-scoped, traversal-safe list/preview/download/upload; writes are approval-gated with versioned snapshots + restore |
| **Artifacts** | per-session artifact listing via adapters |
| **MCP config** | `mcp_servers` on session create, passed through to providers |

## Honest capability states

Nothing is simulated. Every capability is a **named state**:

- `ready` — verified working (binary detected + mechanism confirmed)
- `unverified` — mechanism implemented, not yet exercised end-to-end
- `unavailable:<reason>` — binary absent, auth missing, transport unsupported
- `error` — last operation failed

Handoff distinguishes **`provider-resume`** (verified native resume: Codex,
Devin) from **`context-rebuild`** (reconstructed context — returns
`continuity: "reconstructed"`, never "identical"). Remote runner placement is
**refused** until a health probe verifies the runner.

See [docs/CAPABILITY_MATRIX.md](docs/CAPABILITY_MATRIX.md) for the live matrix
and [docs/HOMOLOGATION.md](docs/HOMOLOGATION.md) for release evidence.

## Install

Two routes — same contract as `productforge install` / `sparkforge-aws install`:

### Bootstrap scripts (user install, no checkout dependence)

| File | Route |
|---|---|
| `install.sh` | POSIX (Linux/macOS) |
| `install.windows.sh` | Windows Git Bash |
| `install.ps1` | Windows PowerShell |
| `scripts/forge_bootstrap.py` | shared engine, driven by `forge.json` |

```bash
./install.sh            # or: install.ps1 / install.windows.sh
./install.sh --dry-run  # plan only
./install.sh --editable # dev mode — CLI tied to this checkout
```

The bootstrap detects Python → builds a wheel → creates a venv at
`~/.forge/installs/forge-agent-bridge` → writes the `forge-bridge` launcher
(`~/.local/bin` / `%USERPROFILE%\.local\bin`) → runs a `forge-bridge --version`
smoke → registers the install under `~/.forge/installations/`.

### `forge-bridge install` (guided wizard / flag path)

Bare on a terminal, `forge-bridge install` runs the guided wizard:
**scope** (`user`·`project`·`workspace`) → **profile**
(`minimal`·`recommended`·`full`) → **components**
(`service`·`state`·`pairing`·`providers`·`config`) → real dry-run plan →
confirm → apply → doctor.

Non-interactive for CI:

```bash
forge-bridge install --yes --scope user --profile recommended
forge-bridge install --dry-run                    # plan JSON, nothing written
forge-bridge install-status                     # per-check verification
forge-bridge uninstall --yes                    # removes generated artifacts —
                                                # NEVER pair.token/events/backups
```

Bridge-honest components (a localhost service ships no host payloads):

| Component | Effect |
|---|---|
| `service` | verifies `forge-bridge` on PATH (`unverified` until bootstrap ran) |
| `state` | `<root>` + `events/` + `backups/` dirs |
| `pairing` | `<root>/pair.token` 0600 (never rotated silently) |
| `providers` | `<root>/providers.json` — capability-matrix snapshot |
| `config` | `<root>/config.json` — seeded limits (rate/quota/retention) |

Default state root by scope: `user` → `~/.forge-bridge`,
`project` → `./.forge-bridge`, `workspace` → `<parent>/.forge-bridge`.

### Dev

```bash
python3 -m pip install -e ".[dev]"
forge-bridge --help
```

No dependencies beyond Python 3.11+ (`typer`, `pydantic`).

## Quickstart

```bash
# 1. Pair — creates ~/.forge-bridge/pair.token (0600)
forge-bridge pair

# 2. Diagnostics — providers detected, auth states
forge-bridge doctor
forge-bridge providers

# 3. Serve the local bridge (127.0.0.1 only)
forge-bridge serve --port 8787

# 4. From any client — bearer auth, agent-session surface
TOKEN=$(cat ~/.forge-bridge/pair.token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/status
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"provider":"claude","product_id":"payments","title":"retry analysis"}' \
     http://127.0.0.1:8787/agent-sessions
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"text":"summarize the retry policy"}' \
     http://127.0.0.1:8787/agent-sessions/{sid}/prompt
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"after_seq":0}' http://127.0.0.1:8787/agent-sessions/{sid}/events
```

## Provider adapters

| Provider | Mechanism | Resume | Status |
|---|---|---|---|
| **Claude Code** | `claude -p --output-format stream-json --input-format stream-json` | context-rebuild | binary detected |
| **Codex CLI** | `codex exec --json` (JSONL); `codex exec resume` | provider-resume | binary detected |
| **Devin** | `devin acp` (ACP stdio JSON-RPC) | provider-resume | binary detected |
| **fake** | in-process scripted events | — | test provider |

All adapters normalize provider output into `forge/AgentBridgeEvent/v1`
envelopes (seq, dedupe, replay buffer, unknown natives preserved in `raw`).

Details: [docs/PROVIDERS.md](docs/PROVIDERS.md).

## HTTP surface

Auth: `Authorization: Bearer <pair.token>` on every request.
Identity: `X-FAB-Principal` (default `local`) — self-asserted; the pair token
is the trust boundary.

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | health, workspace root, running sessions |
| GET | `/providers` | capability matrix (detected + auth states) |
| GET | `/audit` | audit trail tail (`X-Tail` header) |
| POST | `/sessions` | raw process spawn (`cmd` string list) |
| DELETE | `/sessions/{id}` | terminate spawned process |
| POST | `/agent-sessions` | create agent session (provider, product, title, mcp_servers, runner) |
| GET | `/agent-sessions` | list live + closed sessions with metadata |
| PATCH | `/agent-sessions/{sid}` | update metadata (title, favorite, archived, visibility, notes) |
| DELETE | `/agent-sessions/{sid}` | close + archive session |
| POST | `/agent-sessions/{sid}/prompt` | send prompt (text, attachments) — authz + budget gated |
| POST | `/agent-sessions/{sid}/events` | replay events `after_seq` |
| POST | `/agent-sessions/{sid}/cancel` | cancel in-flight turn |
| POST | `/agent-sessions/{sid}/resume` | resume via provider `session_ref` |
| POST | `/agent-sessions/{sid}/approve` | resolve approval (owner/delegated) |
| POST | `/agent-sessions/{sid}/share` | set visibility/observers/delegation |
| POST | `/agent-sessions/{sid}/comment` | append comment |
| POST | `/agent-sessions/{sid}/handoff` | hand off (remote / provider-resume / context-rebuild) |
| POST | `/agent-sessions/{sid}/artifacts` | list session artifacts |
| POST | `/files/{op}` | `list` `preview` `download` `upload` `history` `restore` |
| GET | `/runners` | list runners |
| POST | `/runners` | register remote runner (`unverified`) |
| POST | `/runners/{id}/health` | probe health → `ready`/`error` |
| POST | `/runners/{id}/deregister` | remove remote runner (local refuses) |
| GET | `/budget` | usage summary per scope |
| POST | `/budget/limits` | set limit (scope, key, window, tokens) |

Errors are typed `FAB-*` codes in `{error: {code, message}}` envelopes;
`FORBIDDEN` → 403, `BUDGET` → 429, `NOT-FOUND` → 404, validation → 422,
malformed JSON → 422, adapter errors → 502.

Full reference: [docs/API.md](docs/API.md).

## Security model

- **Localhost only** — binds `127.0.0.1`, never a public interface.
- **Pairing token** — generated `0600`, required on every request.
- **File safety** — root-scoped resolution, `..` traversal rejected, preview
  size cap, mutation ops require `approved: true`, versioned snapshots before
  overwrite, restore support.
- **Authorization** — owner-only actions on private sessions; observers
  read-only; delegated approver can resolve approvals.
- **Budgets** — checked *before* prompt execution; usage recorded from real
  provider `usage.updated` events where available (else `estimated: true`).
- **No secrets** — credentials never reach provider envs or logs.

Details: [docs/SECURITY.md](docs/SECURITY.md).

## Layout

```
src/forge_agent_bridge/
  contracts.py      # 20+ typed entities, CapabilityState
  adapter.py        # ProviderAdapter protocol + FAB-* errors
  events.py         # forge/AgentBridgeEvent/v1 buffer + replay
  registry.py       # declarative provider catalog + detection
  orchestrator.py   # adapter + normalize + buffer in one API
  local_bridge.py   # 127.0.0.1 HTTP surface (auth, routes, error mapping)
  runners.py        # runner registry + health lifecycle
  budgets.py        # scoped limits + usage ledger
  collab.py         # owner/observer/delegated authz + comments
  metadata.py       # persisted session metadata
  files.py          # path-scoped file ops + snapshots
  acp.py            # ACP stdio JSON-RPC client (Devin)
  cli.py            # forge-bridge status|doctor|providers|sessions|pair|serve
  providers/        # claude.py, codex.py, acp_adapter.py, fake.py
tests/              # test_cycle19 … test_cycle24 (35 tests)
docs/               # CAPABILITY_MATRIX, HOMOLOGATION, ADR-001, API, PROVIDERS, SECURITY
```

## Development

```bash
python -m pytest -q            # 35 tests
python -m ruff check src tests # lint
forge-bridge doctor            # environment diagnostics
```

## Consumer

**Forge Portal → Chat Studio** is the primary client: three-column session
workspace (sessions list, stream, context/files) driving every endpoint above
through the `PfApi` bridge service.
