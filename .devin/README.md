# Devin project config — forge-agent-bridge

agent-host bridge — provider adapters (claude/codex/devin/copilot), sessions and context packs.

- CLI: `forge-bridge` (see AGENTS.md for the operating contract).
- Obsidian export: `forge-bridge obsidian status|scan|preview|sync-plan|history` (read verbs pre-allowed in `config.json`; `export`/`export-note` mutate the vault and stay gated).
- `config.json` only declares `permissions` (repo-declarable keys); user-level settings are out of scope.
