#!/usr/bin/env bash
# Non-interactive Laneguard scaffold used by /laneguard:init. All flags are passed to init.py.
# Example:
#   scripts/init.sh --profile standard --project demo --repo acme/demo --owner alice \
#     --engine-sha <40-hex> --validation-test "npm test" --ci node
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo "init: python3 is required" >&2; exit 2; }
exec python3 "$here/init.py" "$@"
