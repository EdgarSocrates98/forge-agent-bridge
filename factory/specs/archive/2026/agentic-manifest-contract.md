---
id: agentic-manifest-contract
title: Forge Agent Bridge agentic capability manifest
status: proposed
created: 2026-11-04
owner: forge-agent-bridge
scope: forge-agent-bridge
cycle: "01"
priority: p0
risk: medium
agent: codex
source: prompt_evo_mastering_melhorias.md §8.5
verification:
  - uv run pytest -q tests/test_manifest_version.py
  - uv build
  - uv run ruff check src tests/test_manifest_version.py
---

# Forge Agent Bridge agentic capability manifest

## Acceptance contract

- Bridge publishes a versioned `forge.agentic.json` for discovery and host
  routing.
- Root and packaged manifests match package version `0.2.0`.
- Workflows reflect verified read-only diagnostics/status surfaces and do not
  claim provider credentials or network access as requirements.
- The wheel contains the manifest and the verification commands pass.
