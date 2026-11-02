# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

- Primary test framework: pytest >=8.
- Assertion/mocking tools: pytest fixtures, fake provider, fake ACP server and portable E2E scripts.
- Commands:

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests
python scripts/e2e_cycle30_1.py
```

### 2) Test Layout

- Central `tests/` with cycle-based regression files and dedicated install/perf tests.
- `scripts/e2e_cycle30_1.py` is a portable harness; `docs/audits/evidence/` stores evidence.

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | yes | contracts, budgets, helpers | broad cycle suite |
| Integration | yes | local bridge/provider fakes/ACP | real provider evidence is separate |
| E2E | yes, repo-local | bridge lifecycle/diagnostics | Product Forge + Portal installed journey is not one required gate |

### 4) Mocking and Isolation Strategy

- Main approach: fake provider and fake ACP server; provider adapters remain replaceable.
- Isolation: dynamic ports/repos and seeded state in portable E2E harness.
- Common failure mode: a repo-local green run can miss cross-repo install/version/token mismatches.

### 5) Coverage and Quality Signals

- Coverage tool/threshold: `[TODO]` — no numeric floor in `pyproject.toml` or CI.
- Strong signals: provider capability matrices, security jobs, SBOM and live homologation docs.
- Gap: credentialed provider tests need controlled nightly execution and redaction assertions.

### 6) Evidence

- `pyproject.toml`
- `.github/workflows/ci.yml`
- `tests/test_install.py`
- `scripts/e2e_cycle30_1.py`
