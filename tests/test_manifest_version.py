"""Capability manifest parity and packaging checks."""

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _version() -> str:
    source = (REPO / "src" / "forge_agent_bridge" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)', source)
    assert match
    return match.group(1)


def test_forge_json_version_matches_pyproject() -> None:
    manifest = json.loads((REPO / "forge.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["version"] == pyproject["project"]["version"]


def test_manifest_versions_and_package_copies() -> None:
    version = _version()
    root_agentic = json.loads((REPO / "forge.agentic.json").read_text(encoding="utf-8"))
    packaged_agentic = json.loads(
        (REPO / "src" / "forge_agent_bridge" / "forge.agentic.json").read_text(encoding="utf-8")
    )
    assert root_agentic == packaged_agentic
    assert root_agentic["version"] == version
    assert root_agentic["provider"] == "forge-agent-bridge"
    root = json.loads((REPO / "forge.json").read_text(encoding="utf-8"))
    packaged = json.loads(
        (REPO / "src" / "forge_agent_bridge" / "forge.json").read_text(encoding="utf-8")
    )
    assert root == packaged
    assert root["version"] == version
