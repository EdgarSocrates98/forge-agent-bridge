# Cycle 30.1 — Final Homologation Report

## HEADs e CI (2026-10-30, todos verdes no GitHub Actions)

| Repo | SHA | CI run | Tests | Lint/Build |
|---|---|---|---|---|
| forge-agent-bridge | `14175d4` | ci success | 94 passed | ruff clean · SBOM válido (103 components) |
| forge-portal | `8ed434b` | forge-portal CI success | 211 py + 579 vitest | ruff clean · ng build · i18n gate · e2e Chromium |
| product-forge | `1fa5f7f` | ci success | 105 passed | ruff clean |

## Correções entregues neste ciclo

- **WS A.1** SBOM CI: `cyclonedx-py environment` recebia `python`
  (inexistente no runner — só `python3`). Fix: `$(command -v python3)`.
  SBOM local reproduzido: CycloneDX JSON válido, 103 components.
- **WS A.2** Portal Format check: 30 arquivos reformatados (prettier).
- **WS A.3** Portal i18n parity (mascarado pela falha de formatação):
  269 literais hardcoded em 22 superfícies `pf/*` do ciclo 29 — codemod
  gerou chaves `pf.*`, traduções pt-BR completas (1256 chaves nos dois
  dicionários), `TPipe` injetado. Build + 579 specs + gate verdes.
- **WS A.4** Portal CI Chromium: `ubuntu-latest` virou 26.04, sem suporte
  no Playwright 1.60 — runner pinado em `ubuntu-24.04`.
- **WS B** segurança (verificada em e2e real): pairing 401/403/201,
  approval gate 409 → deny (bloqueado) → grant → replay e tamper
  rejeitados (`approval token already consumed`), context
  attach/revoke, prompt pós-revogação 403, audit trail completo.
- **ACP real**: `request_async`/`prompt_async`/`session/load` —
  streaming de `session/update` durante o turno (antes só drenava no
  fim), `usage` + `turn_complete` com `stopReason`, resume real.
- **Bedrock provider** (product-forge): `MissingDependencyException` →
  `unavailable:dependency` (honest state, sem traceback).
- **e2e driver** `scripts/e2e_cycle30_1.py`: 3 serviços reais + Chromium.
  Corrigidos: campo `question` (não `q`), rota `/pf/chat`, SPA fallback
  + SO_REUSEADDR. **40 checks, zero falhas.**

## Evidência live — três serviços em navegador real

`docs/audits/evidence/e2e_cycle30_1/` (e2e_log.jsonl + shots/*.png +
fab.log + pf_api.log):

- Sessão Devin real via bridge: prompt `FORGE-E2E-PING-9` respondido,
  36 eventos drenados, usage 136,9k tokens, `turn.completed` com
  `stopReason=end_turn`.
- Resume: `session/load` preserva `provider_session_ref`
  (`debonair-bellflower`, `profuse-jumpsuit`, `flower-nickel` nas 3 runs).
- Aprovações: mint → deny → grant → upload 200 → replay/tamper 403.
- Product Forge: health, products (Payments API + Customer Analytics),
  knowledge query com citação real `chk_3029de4fdc00`, SQL validate +
  execute (3 linhas reais: `4024 CARD_DECLINED 87`), `DROP TABLE`
  rejeitado (read-only enforcement), dashboard `das_07d6e1e01593` +
  render, report `rep_c23755b296d4`, decision `dec_3a35440ee642`,
  budget, audit trail n≥7.
- Portal em Chromium real (`/pf/chat`): sessões visíveis no DOM,
  zero `pageerror`, screenshots em `shots/`.

## Provider homologation (estado honesto)

| Provider | Estado | Evidência |
|---|---|---|
| Devin CLI `3000.11.234` | **live-homologated** (session/stream/usage/resume) | transcript + 3 e2e runs |
| Copilot CLI `1.0.105` | **live-homologated** (prompt/stream/usage/resume) | transcript `copilot_20261030T093705.jsonl` |
| Claude Code `2.1.304` | `unavailable:auth` — "Not logged in" | probe real |
| Codex CLI `0.163.0` | `unavailable:mcp-config` — MCP `token-optimizer` aborta session init | probe real |
| Claude via Bedrock | `unavailable:AccessDeniedException` — conta em verificação | `bedrock_20261030T094324.log` |

Tool calls, approvals in-provider, denial, cancel: `unverified` em
todos os providers (não exercitados live — fake adapter não conta).

## Gaps honestos remanescentes

- Provider tool-call/approval/denial/cancel flows: unverified em todos.
- Claude Code e Codex: precisam de login/config corrigida (ação do usuário).
- Bedrock: aguarda verificação de conta AWS + inference profile `sa-east-1`.
- Pairing sessions efêmeras por decisão documentada (re-pareamento após
  restart do bridge).
- Windows Job Objects: sem host Windows em CI.
- `product_id` bind: validação server-side contra PF segue `unverified`
  (sem endpoint de lookup).
- Diagnostic Center unificado (§11): checks reais existem distribuídos —
  Control Center (sessões/approvals/providers/auth_state via API live),
  Settings (teste de conexão PF), Health tab, Lens (context health,
  provider routing, budgets). Uma página de diagnóstico consolidada
  com ações corretivas por check não existe — cobertura parcial.
- Compat checker de versões Claude/Codex/Devin (§11): não implementado;
  versões testadas registradas na capability matrix, futuras = Unverified.
- `test_perf_smoke` teve 1 flake em CI (`ConnectionResetError` em 1/20
  sessões concorrentes) — rerun verde, local estável; observar.

## Performance (medição existente, ciclo 30)

1 sessão 0.01s · 5 concorrentes 0.04s · 20 concorrentes 1.04s
(15× FAB-QUOTA sob cap de 8 runners) · replay 5000 eventos 0.04s.

## Classificação final: **Ready with restrictions**

Restrições:
1. Apenas Devin e Copilot são live-homologated (session/stream/usage/
   resume). Claude Code/Codex/Bedrock indisponíveis por auth/config/conta —
   providers não homologados não devem ser oferecidos em produção.
2. Capacidades de tool-call, aprovação in-provider, denial e cancel
   permanecem `unverified` em todos os providers.
3. Pairing sessions são efêmeras — re-pareamento após restart do bridge.

O que mudou vs. o relatório anterior: browser E2E e Payments API E2E
executados de verdade (40 checks verdes + screenshots); Devin e
Copilot homologados com evidência live; as três CIs verdes no HEAD.
