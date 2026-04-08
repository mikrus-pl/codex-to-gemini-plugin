#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

/usr/bin/python3 "$REPO_DIR/scripts/install_global_plugin.py"

# Open folders in Finder so hidden paths are easy to inspect.
mkdir -p "$HOME/.codex/plugins" "$HOME/.agents/plugins"
open "$HOME/.codex/plugins"
open "$HOME/.agents/plugins"

echo ""
echo "Done. Press Enter to close this window."
read -r
