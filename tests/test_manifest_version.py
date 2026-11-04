"""forge.json version must match the package version (single source of truth)."""

import json
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_forge_json_version_matches_pyproject() -> None:
    manifest = json.loads((REPO / "forge.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = pyproject["project"]["version"]
    assert manifest["version"] == package_version, (
        f"forge.json version {manifest['version']} diverges from "
        f"pyproject version {package_version}"
    )
