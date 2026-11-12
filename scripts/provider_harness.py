#!/usr/bin/env python3
"""Real provider homologation harness.

The harness deliberately writes metadata only: never prompts, tokens, provider
responses, environment values, or raw stderr.  It is safe for CI artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge_agent_bridge.adapter import (
    AuthenticationError,
    BridgeError,
    ProviderUnavailableError,
)
from forge_agent_bridge.registry import REGISTRY

PROVIDERS = ("codex", "claude-code", "devin", "github-copilot")
SECRET_WORDS = re.compile(r"(?i)(token|secret|password|api[_-]?key|cookie|authorization)\s*[:=]\s*\S+")


def redact(value: str, limit: int = 240) -> str:
    """Keep diagnostics useful without allowing common secret formats through."""
    value = SECRET_WORDS.sub(r"\1=[REDACTED]", value)
    value = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(r"\b(sk-[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_]+)\b", "[REDACTED]", value)
    return " ".join(value.split())[:limit]


def result_template(provider_id: str, executable: str | None) -> dict[str, Any]:
    return {
        "id": provider_id,
        "executable": executable,
        "version": None,
        "auth_state": "unverified",
        "status": "unverified",
        "event_count": 0,
        "event_types": [],
        "error_code": None,
        "error_detail_redacted": None,
    }


def run_provider(provider_id: str, prompt: str, timeout_s: float) -> dict[str, Any]:
    descriptor = next((item for item in REGISTRY.detect_all() if item.id == provider_id), None)
    adapter = REGISTRY.adapter(provider_id)
    row = result_template(provider_id, descriptor.executable if descriptor else None)
    if adapter is None:
        row.update(status="unavailable", error_code="FAB-UNAVAILABLE",
                   error_detail_redacted="provider executable is not installed")
        return row
    try:
        row["version"] = redact(adapter.get_version() or "") or None
        row["auth_state"] = redact(str(adapter.get_auth_status()))
        if row["auth_state"] in {"unauthenticated", "expired"}:
            detail = "provider login is required before a real prompt can run"
            if provider_id == "claude-code":
                detail = "Claude subscription/API key missing; Bedrock AWS session may also be expired"
            row.update(status="blocked", error_code="FAB-AUTH", error_detail_redacted=detail)
            return row
        adapter.initialize()
        session = adapter.create_session(cwd=os.environ.get("FAB_PROVIDER_WORKDIR") or ".")
        try:
            adapter.send_prompt(session.id, prompt)
            events = list(adapter.stream_events(session.id))
            row["event_count"] = len(events)
            row["event_types"] = sorted({str(event.get("type", "unknown")) for event in events})
            row["status"] = "passed" if events else "error"
            if not events:
                row.update(error_code="FAB-NO-EVENTS", error_detail_redacted="provider returned no events")
        finally:
            try:
                adapter.close_session(session.id)
            finally:
                adapter.dispose()
        return row
    except AuthenticationError as exc:
        row.update(status="blocked", error_code=exc.code,
                   error_detail_redacted=redact(exc.message))
    except ProviderUnavailableError as exc:
        row.update(status="unavailable", error_code=exc.code,
                   error_detail_redacted=redact(exc.message))
    except BridgeError as exc:
        row.update(status="error", error_code=exc.code,
                   error_detail_redacted=redact(exc.message))
    except Exception as exc:  # noqa: BLE001 - harness must report, never crash the matrix
        row.update(status="error", error_code="HARNESS-UNEXPECTED",
                   error_detail_redacted=redact(f"{type(exc).__name__}: {exc}"))
    finally:
        try:
            adapter.dispose()
        except Exception:  # noqa: BLE001, S110 - cleanup must not hide the recorded result
            pass
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", help="run real provider CLIs")
    parser.add_argument("--prompt", default="Reply exactly READY.", help="synthetic prompt")
    parser.add_argument("--timeout", type=float, default=150.0, help="timeout per provider")
    parser.add_argument("--output", type=Path, help="write redacted JSON artifact")
    args = parser.parse_args()
    if not args.real:
        parser.error("--real is required; use the test suite for fake-provider contract tests")
    prompt_hash = hashlib.sha256(args.prompt.encode()).hexdigest()
    rows: list[dict[str, Any]] = []
    for provider_id in PROVIDERS:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(run_provider, provider_id, args.prompt, args.timeout)
        try:
            rows.append(future.result(timeout=args.timeout))
        except TimeoutError:
            rows.append({**result_template(provider_id, None), "status": "error",
                         "error_code": "HARNESS-TIMEOUT",
                         "error_detail_redacted": f"provider exceeded {args.timeout:.0f}s"})
        finally:
            # A provider subprocess may outlive the reporting deadline. Do not
            # make the harness hang while waiting for an external CLI.
            pool.shutdown(wait=False, cancel_futures=True)
    artifact = {
        "schema": "forge/provider-homologation/1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "prompt_sha256": prompt_hash,
        "providers": rows,
    }
    encoded = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    # `error` rows are harness/adapter failures (crash, timeout, no events) —
    # those are the regressions this matrix exists to catch, so they fail the
    # job. `blocked` (missing auth) and `unavailable` (CLI not installed) are
    # environment states the artifact reports truthfully; a nightly run with
    # no provider credentials must surface them without staying red forever.
    return 2 if any(row["status"] == "error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
