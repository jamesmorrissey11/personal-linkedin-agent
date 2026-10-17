#!/usr/bin/env bash
# Remove current launchd agents and the retired apply-run agent if it is still installed.
set -euo pipefail

DEST="$HOME/Library/LaunchAgents"
for target in "$DEST"/com.personal-linkedin-agent.*.plist; do
  [ -e "$target" ] || continue
  launchctl bootout "gui/$(id -u)" "$target" 2>/dev/null || true
  rm -f "$target"
  echo "Removed $(basename "$target")"
done
