#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ryan Howell
# Installs TallyForth for the current user (no Flatpak) and adds it to the application menu.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
ID="io.github.ryanghowell.TallyForth"
DEST="$HOME/.local/share/tallyforth-app"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$DEST" "$APPS" "$ICONS" "$HOME/.local/bin"
install -m 755 "$SRC/tallyforth.py" "$DEST/tallyforth.py"
install -m 644 "$SRC/tapecore.py" "$DEST/tapecore.py"
install -m 644 "$SRC/data/$ID.svg" "$ICONS/$ID.svg"
ln -sf "$DEST/tallyforth.py" "$HOME/.local/bin/tallyforth"
sed "s|^Exec=.*|Exec=python3 $DEST/tallyforth.py|" "$SRC/data/$ID.desktop" > "$APPS/$ID.desktop"

# Remove menu entries from earlier versions (your tapes are kept).
rm -f "$APPS/com.example.PaperTape.desktop" "$APPS/com.example.TallyForth.desktop" "$HOME/.local/bin/papertape"
rm -rf "$HOME/.local/share/papertape-app"

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Installed. Look for \"TallyForth\" in your menu, or run: tallyforth"
