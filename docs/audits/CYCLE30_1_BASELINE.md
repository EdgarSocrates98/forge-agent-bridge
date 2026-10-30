# Cycle 30.1 Baseline Audit

| Repositório | HEAD auditado | Testes | Lint |
|---|---|---|---|
| forge-agent-bridge | `67a33c1` → `b8543a8` | 86 → 93 passed | ruff clean |
| forge-portal | `3dd21e6` → `4570b77` | 211 py + 579 vitest | ruff clean (was failing) |
| product-forge | `785b717` | 100 passed | ruff clean |

## Revalidated findings

| # | Finding | Classificação | Evidência |
|---|---|---|---|
| A.1 | Bridge CI `security` job fails at `SBOM (CycloneDX)` — `cyclonedx-py` v7 renamed flags (`--output-format/--outfile` → `--of/-o`) | **Confirmed → fixed** | reproduzido localmente: `unrecognized arguments: --outfile`; corrigido em `.github/workflows/ci.yml` com `cyclonedx-bom>=7,<8` + `cyclonedx-py environment python --of JSON -o sbom.json` + validação JSON |
| A.2 | Portal CI fails at `Ruff` | **Confirmed → fixed** | 15 erros reais (E402/I001/UP017/RUF100) em `portal_core/tests/scripts/e2e`; `--fix` aplicado; `forge_portal.py` revertido (vendored byte-parity) e excluído via `ruff.toml` per-file-ignore |
| A.2b | `test_inventory_schema_fields` pinned literal `0.1.0` vs package `1.0.0` | **New → fixed** | assert agora lê `package.json` |
| A.2c | `test_vendored_checkout_copies_match_or_are_known_drift` | **Regression caused by lint fix → fixed** | canonical revertido; byte-parity restaurada |
| B.1 | `assert_allowed` sem negação para contexto revogado; allowlist vazia = irrestrita para tools restritas | **Confirmed → fixed** | `trust`, `context.revoked`, `RESTRICTED_TOOLS` deny-by-default, `require_context` |
| B.3/B.4 | Approval consume não-atômico; sem actor binding no consume | **Confirmed → fixed** | `threading.Lock` em `resolve`/`consume`; grant guarda `requester`; consume valida actor |
| B.5 | `_origin_ok` só validava hostname | **Confirmed → fixed** | scheme http/https + host loopback + port válida + `FAB_ALLOWED_ORIGINS` exata |
| B.7 | Pairing session tokens em memória | **Confirmed → decisão documentada** | Opção A (efêmeras) — restart exige re-pareamento; ver SECURITY.md |
| 11.3 | Sem integrity checker | **New → implemented** | `integrity.py` + `GET /intel/{sid}/integrity` (forge/SessionIntegrity/v1) |

## Provider versions (this host)

- claude `2.1.304` · codex `0.163.0` · devin `3000.11.234` — all `unverified` (see LIVE_CAPABILITY_MATRIX.md).

## Not verified in this baseline

- Live provider flows (credentials not confirmed in-scope).
- Full Playwright browser E2E against the 3 running services.
- Windows Job Objects (no Windows CI host).
