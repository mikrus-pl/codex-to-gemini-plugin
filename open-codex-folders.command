#!/bin/bash
set -euo pipefail

mkdir -p "$HOME/.codex/plugins" "$HOME/.agents/plugins"
open "$HOME/.codex"
open "$HOME/.codex/plugins"
open "$HOME/.agents/plugins"

echo "Opened ~/.codex and ~/.agents/plugins in Finder."
echo "Press Enter to close this window."
read -r
