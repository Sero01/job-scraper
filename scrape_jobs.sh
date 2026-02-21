#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd '$(dirname "${BASH_SOURCE[0]}")' && pwd)"

echo "Starting job scraper..."
uv run "$SCRIPT_DIR/job_scraper.py"
