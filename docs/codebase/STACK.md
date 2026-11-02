# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

| Area | Value | Evidence |
|------|-------|----------|
| Primary language | Python | `pyproject.toml`, `src/forge_agent_bridge/` |
| Runtime + version | Python >=3.11; CI 3.12 | `pyproject.toml`, `.github/workflows/ci.yml` |
| Package manager | pip/PEP 517 wheel; bootstrap scripts | `pyproject.toml`, `install.sh` |
| Module/build system | Hatchling | `pyproject.toml` |

### 2) Production Frameworks and Dependencies

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| Pydantic | >=2.6 | typed session/event contracts | `pyproject.toml` |
| Typer | >=0.12 | `forge-bridge` CLI | `pyproject.toml` |
| Python stdlib HTTP | stdlib | local bridge server | `README.md`, `src/forge_agent_bridge/local_bridge.py` |

### 3) Development Toolchain

| Tool | Purpose | Evidence |
|------|---------|----------|
| pytest | unit/integration tests | `pyproject.toml`, `tests/` |
| Ruff | lint | `pyproject.toml`, CI |
| pip-audit/CycloneDX | supply-chain gates | `.github/workflows/ci.yml` |

### 4) Key Commands

```bash
./install.sh
forge-bridge install --yes
forge-bridge doctor
python -m pytest -q
python -m ruff check src tests
```

### 5) Environment and Config

- Config sources: `forge.json`, CLI flags, pairing token under `~/.forge-bridge/`, provider environment/auth state.
- Required env vars: `[TODO]`; no `.env.example` was found by the scan.
- Runtime constraint: local HTTP bridge binds to `127.0.0.1` and uses bearer pairing.

### 6) Evidence

- `pyproject.toml`
- `forge.json`
- `README.md`
- `install.sh`
