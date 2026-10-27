#!/usr/bin/env bash
# Install a per-user menu entry whose desktop ID stays app.berrylink.desktop.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor/scalable/apps"

if [[ ! -x "$ROOT/scripts/run-desktop.sh" ]]; then
    echo "Missing executable launcher: scripts/run-desktop.sh" >&2
    exit 1
fi

mkdir -p "$APPS" "$ICONS"
escaped_root="${ROOT//&/\\&}"
sed "s|@ROOT@|$escaped_root|g" \
    "$ROOT/packaging/app.berrylink.desktop.in" \
    > "$APPS/app.berrylink.desktop"
install -m 0644 \
    "$ROOT/packaging/app.berrylink.desktop.svg" \
    "$ICONS/app.berrylink.desktop.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS" >/dev/null 2>&1 || true
fi

echo "Installed $APPS/app.berrylink.desktop"
