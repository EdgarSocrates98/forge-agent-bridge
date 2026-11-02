# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Files | snake_case | `local_bridge.py` | source tree |
| Functions/methods | snake_case | orchestration and adapter methods | `src/` |
| Types/interfaces | PascalCase | typed contract models | `contracts.py` |
| Constants/env vars | uppercase/explicit config names | `[TODO]` | `src/`, docs |

### 2) Formatting and Linting

- Formatter: `[TODO]` — no formatter config is declared at root.
- Linter: Ruff, line length 110 (`pyproject.toml`).
- Run commands: `python -m ruff check src tests`; `python -m pytest -q`.

### 3) Import and Module Conventions

- Standard Python imports; no alias policy is declared.
- Public behavior is expressed through the typed contracts and CLI entry point.

### 4) Error and Logging Conventions

- Capability failures are represented honestly as ready/unverified/unavailable/error.
- Audit and diagnostic surfaces exist; sensitive logging/redaction coverage is documented in `docs/SECURITY.md` and `[TODO]` for full system proof.

### 5) Testing Conventions

- Tests are centralized in `tests/test_*.py`.
- Fake provider and fake ACP server support deterministic integration tests.
- Coverage threshold: `[TODO]` — CI runs tests and lint but does not declare a numeric floor.

### 6) Evidence

- `pyproject.toml`
- `.github/workflows/ci.yml`
- `tests/test_bridge.py`
- `tests/test_cycle30_2.py`
