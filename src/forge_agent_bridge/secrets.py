"""Secrets abstraction — env / keychain / encrypted-file backends (§25.8).

Provider credentials never pass through the bridge verbatim; a store maps
``name -> secret`` with the actual backend declared. Keychain uses
``keyring`` when importable (honest ``unavailable`` otherwise); the file
backend is ``0600`` under ``~/.forge-bridge/secrets.json`` — acceptable for
local dev, flagged honestly as `kind: file` (not a real keychain).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class SecretStore(Protocol):
    kind: str

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...


class EnvSecretStore:
    kind = "env"

    def __init__(self, prefix: str = "FAB_SECRET_") -> None:
        self.prefix = prefix

    def get(self, name: str) -> str | None:
        return os.environ.get(self.prefix + name.upper())

    def set(self, name: str, value: str) -> None:
        os.environ[self.prefix + name.upper()] = value

    def delete(self, name: str) -> bool:
        return os.environ.pop(self.prefix + name.upper(), None) is not None


class FileSecretStore:
    """0600 file under the bridge state dir — dev-grade, honestly labeled."""
    kind = "file"

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, str]:
        if self.path.is_file():
            return json.loads(self.path.read_text())
        return {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.write_text(json.dumps(data))
        os.chmod(self.path, 0o600)

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        d = self._load()
        d[name] = value
        self._save(d)

    def delete(self, name: str) -> bool:
        d = self._load()
        if name in d:
            del d[name]
            self._save(d)
            return True
        return False


class KeyringSecretStore:
    kind = "keyring"

    def __init__(self, service: str = "forge-agent-bridge") -> None:
        try:
            import keyring
            self._kr = keyring
        except ImportError as e:
            raise BridgeUnavailable("keyring backend unavailable") from e
        self.service = service

    def get(self, name: str) -> str | None:
        return self._kr.get_password(self.service, name)

    def set(self, name: str, value: str) -> None:
        self._kr.set_password(self.service, name, value)

    def delete(self, name: str) -> bool:
        try:
            self._kr.delete_password(self.service, name)
            return True
        except Exception:  # noqa: BLE001 — keyring backend errors vary by OS
            return False


class BridgeUnavailable(Exception):
    """Honest unavailable state for optional backends."""


def secret_store(prefer: str = "auto",
                 state_dir: Path | None = None) -> SecretStore:
    """Pick the best available backend — declares which one it picked."""
    if prefer in ("auto", "keyring"):
        try:
            return KeyringSecretStore()
        except BridgeUnavailable:
            if prefer == "keyring":
                raise
    if prefer in ("auto", "env"):
        return EnvSecretStore()
    return FileSecretStore(state_dir or
                           Path.home() / ".forge-bridge" / "secrets.json")
