#!/usr/bin/env bash
# unit-tests.sh — run the complete unit test suite through SearXNG's managed environment.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
exec ./manage test.unit
