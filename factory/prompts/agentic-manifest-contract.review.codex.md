Review Loop Factory spec `agentic-manifest-contract` against current working tree.

        Native adapter: `codex`
        Spec path: `E:\projetos\FORJAS\forge-agent-bridge\factory\specs\active\agentic-manifest-contract.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `uv run pytest -q tests/test_manifest_version.py`
- `uv build`
- `uv run ruff check src tests/test_manifest_version.py`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

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
