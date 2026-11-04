You are implementing Loop Factory spec `agentic-manifest-contract`.

        Native adapter: `codex`
        Spec path: `E:\projetos\FORJAS\forge-agent-bridge\factory\specs\active\agentic-manifest-contract.md`
        Spec hash: `6b8ada965dbef2ad487aefe42c9aea4f9aaa6b4a2795aba3edd924f667ce0476`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

        Required verification:
        - `uv run pytest -q tests/test_manifest_version.py`
- `uv build`
- `uv run ruff check src tests/test_manifest_version.py`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Forge Agent Bridge agentic capability manifest

## Acceptance contract

- Bridge publishes a versioned `forge.agentic.json` for discovery and host
  routing.
- Root and packaged manifests match package version `0.2.0`.
- Workflows reflect verified read-only diagnostics/status surfaces and do not
  claim provider credentials or network access as requirements.
- The wheel contains the manifest and the verification commands pass.
