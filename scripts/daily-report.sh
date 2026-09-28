#!/usr/bin/env bash
# Run on the VPS as the same user as the existing stack watchdog.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PATH:/usr/local/bin"
if [ -f .env ]; then
    set -a
    source ./.env
    set +a
fi
exec python3 scripts/daily_report.py "$@"
