#!/usr/bin/env bash
# Install the launchd agents for the daily LinkedIn run (macOS). Safe to re-run.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv not found on PATH" >&2; exit 1; }
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST" "$REPO/logs"

for template in "$REPO"/scheduling/*.plist; do
  name="$(basename "$template")"
  target="$DEST/$name"
  sed -e "s|__REPO__|$REPO|g" -e "s|__UV__|$UV|g" -e "s|__UV_DIR__|$(dirname "$UV")|g" "$template" > "$target"
  launchctl bootout "gui/$(id -u)" "$target" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$target"
  echo "Installed $name"
done
