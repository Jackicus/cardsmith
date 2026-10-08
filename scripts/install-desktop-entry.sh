#!/usr/bin/env sh
# Add Cardsmith to your Linux app menu (uses the cardsmith-gui in .venv or on PATH).
set -e
here="$(cd "$(dirname "$0")/.." && pwd)"
exe="$here/.venv/bin/cardsmith-gui"
[ -x "$exe" ] || exe="$(command -v cardsmith-gui || true)"
[ -n "$exe" ] || { echo "cardsmith-gui not found – install first: pip install -e '.[gui]'"; exit 1; }
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$icons" "$apps"
cp "$here/src/cardsmith/gui/icon.svg" "$icons/cardsmith.svg"
cat > "$apps/cardsmith.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Cardsmith
GenericName=3D-printable flashcards
Comment=Turn spreadsheets into multi-colour 3D-printable cards
Exec="$exe" %f
Icon=cardsmith
Terminal=false
Categories=Graphics;3DGraphics;Education;
MimeType=text/csv;text/tab-separated-values;
DESK
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true
echo "Installed: $apps/cardsmith.desktop"
