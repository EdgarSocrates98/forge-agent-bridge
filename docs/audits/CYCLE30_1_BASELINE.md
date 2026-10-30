# Cycle 30.1 Baseline Audit

Atualizado em 2026-10-30 (pós-remediação). HEADs finais e CI:

| Repositório | HEAD inicial | HEAD final | CI final | Testes | Lint/Build |
|---|---|---|---|---|---|
| forge-agent-bridge | `67a33c1` | `14175d4` | ✅ success | 94 passed | ruff clean · SBOM ok |
| forge-portal | `3dd21e6` | `8ed434b` | ✅ success | 211 py + 579 vitest | ruff · ng build · i18n · e2e |
| product-forge | `785b717` | `1fa5f7f` | ✅ success | 105 passed | ruff clean |

## Revalidated findings

| # | Finding | Classificação | Evidência |
|---|---|---|---|
| A.1 | Bridge CI `security` job fails at SBOM step | **Confirmed → fixed** | `cyclonedx-py environment python` — runner só tem `python3`; fix `$(command -v python3)` em `f6e7cec`; SBOM local válido, 103 components; CI verde |
| A.2 | Portal CI fails (Format check → i18n parity → Chromium) | **Confirmed → fixed** | prettier em 30 arquivos (`5fb4544`); 269 literais i18n codemodados p/ `pf.*` keys + pt-BR (`c89a048`); runner pinado `ubuntu-24.04` p/ Playwright (`8ed434b`); CI verde |
| A.2b | `test_inventory_schema_fields` pinned literal vs package | **New → fixed** | assert lê `package.json` |
| A.2c | `test_vendored_checkout_copies_match` | **Regression → fixed** | canonical revertido; byte-parity |
| A.3 | Product Forge CI lint em `bedrock_provider.py` | **New → fixed** | E501+I001 no import multi-name (`1fa5f7f`) |
| B.1 | Contexto revogado não bloqueava; allowlist vazia permissiva | **Confirmed → fixed** | verificado em e2e: `revoked-prompt-403` |
| B.3/B.4 | Approval consume não-atômico; sem actor binding | **Confirmed → fixed** | e2e: `replay-blocked`, `tamper-blocked` 403 |
| B.5 | Origin só validava hostname | **Confirmed → fixed** | scheme+host+port |
| B.7 | Pairing tokens em memória | **Confirmed → decisão documentada** | Opção A efêmeras — SECURITY.md |
| 11.3 | Sem integrity checker | **New → implemented** | `GET /intel/{sid}/integrity` |
| D | Browser E2E 3 serviços | **Unverified → verified** | `scripts/e2e_cycle30_1.py`: 40 checks verdes, Chromium real |
| §12 | Payments API flow | **Unverified → verified** | SQL/dashboard/report/decision/budget/audit via API real |
| C | Provider homologation | **Partially fixed** | Devin+Copilot live; Claude `unavailable:auth`; Codex `unavailable:mcp-config`; Bedrock `unavailable:AccessDeniedException` |

## Provider versions (this host)

- devin `3000.11.234` — live-homologated (session/stream/usage/resume)
- copilot `1.0.105` — live-homologated (prompt/stream/usage/resume)
- claude `2.1.304` — `unavailable:auth` ("Not logged in")
- codex `0.163.0` — `unavailable:mcp-config` (MCP `token-optimizer` aborta init)

Detalhes: `docs/providers/LIVE_CAPABILITY_MATRIX.md`,
`docs/audits/CYCLE30_1_FINAL_HOMOLOGATION.md`,
`docs/audits/evidence/e2e_cycle30_1/`.

## Not verified in this baseline

- Provider tool-call / in-provider approval / denial / cancel flows.
- Windows Job Objects (sem host Windows em CI).
- Server-side `product_id` lookup contra PF (sem endpoint dedicado).
