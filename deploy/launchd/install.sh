#!/usr/bin/env bash
# Install the launchd agents for the daily LinkedIn run (macOS). Safe to re-run.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv not found on PATH" >&2; exit 1; }
DEST="$HOME/Library/LaunchAgents"
# Logs go to the per-user runtime folder; ask the package so this always matches the Python side.
LOGS="$("$UV" run --project "$REPO" python -c 'from linkedin_agent.runtime import logs_dir; print(logs_dir())')"
mkdir -p "$DEST" "$LOGS"

for template in "$HERE"/*.plist; do
  name="$(basename "$template")"
  target="$DEST/$name"
  sed -e "s|__REPO__|$REPO|g" -e "s|__LOGS__|$LOGS|g" -e "s|__UV__|$UV|g" -e "s|__UV_DIR__|$(dirname "$UV")|g" "$template" > "$target"
  launchctl bootout "gui/$(id -u)" "$target" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$target"
  echo "Installed $name"
done
