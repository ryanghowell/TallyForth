#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ryan Howell
# Installs TallyForth for the current user and adds it to the application menu.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/tallyforth-app"
APPS="$HOME/.local/share/applications"

mkdir -p "$DEST" "$APPS" "$HOME/.local/bin"
install -m 755 "$SRC/tallyforth.py" "$DEST/tallyforth.py"
install -m 644 "$SRC/tapecore.py" "$DEST/tapecore.py"
ln -sf "$DEST/tallyforth.py" "$HOME/.local/bin/tallyforth"

# Remove a copy installed back when the app was called Paper Tape (your tapes are kept).
rm -f "$APPS/com.example.PaperTape.desktop" "$APPS/com.example.TallyForth.desktop" "$HOME/.local/bin/papertape"
rm -rf "$HOME/.local/share/papertape-app"

cat > "$APPS/io.github.ryanghowell.TallyForth.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TallyForth
Comment=Tape calculator with notes alongside the numbers
Exec=python3 $DEST/tallyforth.py
Icon=accessories-calculator
Terminal=false
Categories=Utility;Calculator;Office;
Keywords=calculator;tape;adding;tally;receipt;
StartupWMClass=tallyforth.py
EOF

update-desktop-database "$APPS" 2>/dev/null || true
echo "Installed. Look for \"TallyForth\" in your menu, or run: tallyforth"
