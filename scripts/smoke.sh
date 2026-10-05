#!/usr/bin/env sh
# Runs the end-to-end smoke test against a running compose stack.
# Usage: scripts/smoke.sh [base_url]   (default http://localhost:8080)
set -eu
cd "$(dirname "$0")/../backend"
exec uv run python scripts/smoke.py "${1:-http://localhost:8080}"
