#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

/usr/bin/python3 "$REPO_DIR/scripts/install_global_plugin.py"

echo ""
echo "Migration finished. Restart Codex and open a new task."
echo "Press Enter to close this window."
read -r
