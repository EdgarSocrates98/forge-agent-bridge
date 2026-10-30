#!/usr/bin/env bash
# Cycle 30 unified release gate — runs every repo's real verification and
# fails the release if ANY check fails. Order: bridge -> product-forge ->
# portal. No step is optional; a skipped tool is a failed gate.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"   # .../forjas/
BRIDGE="$ROOT/forge-agent-bridge"
PF="$ROOT/product-forge"
PORTAL="$ROOT/forge-portal"

fail=0
step() { echo "=== $* ==="; }
run()  { if "$@"; then echo "PASS: $*"; else echo "FAIL: $*"; fail=1; fi }

step "forge-agent-bridge"
(cd "$BRIDGE" && run .venv/bin/python -m ruff check src tests)
(cd "$BRIDGE" && run .venv/bin/python -m pytest tests -q)

step "product-forge"
(cd "$PF" && run .venv/bin/python -m ruff check src tests)
(cd "$PF" && run .venv/bin/python -m pytest -q)
(cd "$PF" && run .venv/bin/productforge install --dry-run || run .venv/bin/python -m product_forge.cli install --dry-run)
(cd "$PF" && run .venv/bin/python -m product_forge.cli doctor || true)

step "forge-portal"
(cd "$PORTAL" && run npx ng build --configuration production)
(cd "$PORTAL" && run npx ng test --watch=false)

step "RESULT"
if [ "$fail" -ne 0 ]; then
  echo "RELEASE GATE: FAILED"
  exit 1
fi
echo "RELEASE GATE: PASSED"
