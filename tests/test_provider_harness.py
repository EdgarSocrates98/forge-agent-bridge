import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "provider_harness", Path(__file__).parents[1] / "scripts" / "provider_harness.py"
)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
redact = _module.redact


def test_harness_redacts_common_secrets():
    value = "token=abc123 Bearer xyz sk-test-value ghp_123"
    redacted = redact(value)
    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert "sk-test-value" not in redacted
    assert "ghp_123" not in redacted
