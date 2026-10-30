# Cycle 30.1 — Final Homologation Report

## HEADs

| Repo | SHA | Tests | Lint/Build |
|---|---|---|---|
| forge-agent-bridge | `b8543a8` | 93 passed (7 new 30.1 tests) | ruff clean |
| forge-portal | `4570b77` | 211 py · 579 vitest | ruff clean · ng build clean |
| product-forge | `785b717` | 100 passed | ruff clean |

## Correções entregues

- **WS A.1** SBOM CI: root cause real — `cyclonedx-py` v7 removeu
  `--output-format/--outfile`. Fix: pin `cyclonedx-bom>=7,<8`,
  `cyclonedx-py environment python --of JSON -o sbom.json`, JSON
  validado antes do upload. SBOM local reproduzido: CycloneDX válido,
  50 components.
- **WS A.2** Portal Ruff: 15 erros corrigidos; arquivo canônico vendored
  revertido e protegido por `ruff.toml` per-file-ignore justificado;
  teste de versão desfixado do literal.
- **WS B.1** Context authorization: `trust`/revoke, `POST /context/revoke`,
  `RESTRICTED_TOOLS` deny-by-default, `require_context` policy,
  expired/revoked bloqueiam.
- **WS B.3/B.4** Approvals: consumo atômico sob `threading.Lock`
  (teste de corrida com `threading.Barrier`), grant guarda `requester`,
  consume valida actor.
- **WS B.5** Origin policy: scheme+host+port + `FAB_ALLOWED_ORIGINS`;
  malformed/non-web/external rejeitados.
- **WS B.7** Pairing: Opção A documentada (sessões efêmeras).
- **WS B.8** Audit: novos tipos `context.*`, `approval.consumed`,
  `authorization.denied`, `pair.*`, `device.revoked`.
- **WS 11.3** `forge/SessionIntegrity/v1`: missing/dup events, invalid
  cursor, orphan pid, expired approval, broken provider ref, missing
  artifact, corrupted metadata — `GET /intel/{sid}/integrity`.

## Security findings resolvidos

Race em approval consume; allowlist vazia permissiva p/ tools restritas;
contexto revogado não bloqueava; origin só validava hostname; SBOM step
quebrada; ruff failures no portal CI.

## Gaps honestos (não verificados neste ciclo)

- **Provider homologation**: claude `2.1.304`, codex `0.163.0`,
  devin `3000.11.234` detectados, **nenhum exercitado live** —
  credenciais não confirmadas no escopo. Matrix: `docs/providers/
  LIVE_CAPABILITY_MATRIX.md`.
- **Browser E2E (Playwright)**: não executado — requer os 3 serviços +
  navegador real em ambiente dedicado.
- **Windows Job Objects**: sem host Windows em CI.
- **Payments API E2E (§12)**: depende do item anterior + credenciais.
- Product Forge ↔ Bridge product_id validation call (B.2): o bind registra
  o `product_id` declarado; validação server-side contra Product Forge
  permanece `unverified` sem um endpoint de lookup no PF.

## Performance (medição existente, ciclo 30)

1 sessão 0.01s · 5 concorrentes 0.04s · 20 concorrentes 1.04s
(15× FAB-QUOTA sob cap de 8 runners) · replay 5000 eventos 0.04s.

## Classificação final: **Ready with restrictions**

Restrições: (1) nenhum provider live-homologado — usar apenas o fake
adapter em demos até homologação com credenciais; (2) pairing sessions
são efêmeras — re-pareamento após restart do bridge; (3) browser E2E e
Payments E2E pendentes de ambiente com credenciais.
