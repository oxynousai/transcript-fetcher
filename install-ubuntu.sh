#!/usr/bin/env bash
# Install the Udemy Transcript Fetcher desktop app for the current user on Ubuntu:
# a private Python environment, an app launcher with an icon, and a dock favorite.
#
#   ./install-ubuntu.sh              install or update
#   ./install-ubuntu.sh --uninstall  remove the app, its launcher and saved settings
set -euo pipefail

APP_ID=transcript-fetcher
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_DIR/$APP_ID"
VENV="$APP_DIR/venv"
DESKTOP_FILE="$DATA_DIR/applications/$APP_ID.desktop"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"

# Print the dock favorites with $APP_ID added (add) or removed (remove), or nothing if unchanged.
edit_favorites() {
    python3 - "$1" "$2" <<'PY'
import ast, sys
action, current = sys.argv[1], sys.argv[2].strip()
apps = ast.literal_eval(current[3:].strip() if current.startswith("@as") else current)
entry = "transcript-fetcher.desktop"
if action == "add" and entry not in apps:
    print(repr(apps + [entry]))
elif action == "remove" and entry in apps:
    print(repr([a for a in apps if a != entry]))
PY
}

update_dock() {
    command -v gsettings >/dev/null || return 0
    local current new
    current="$(gsettings get org.gnome.shell favorite-apps 2>/dev/null)" || return 0
    new="$(edit_favorites "$1" "$current")" || return 0
    if [[ -n "$new" ]]; then
        gsettings set org.gnome.shell favorite-apps "$new"
    fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
    update_dock remove
    rm -rf "$APP_DIR" "$CONFIG_DIR"
    rm -f "$DESKTOP_FILE"
    echo "Removed Udemy Transcript Fetcher (transcripts you saved are untouched)."
    exit 0
fi

if ! command -v python3 >/dev/null; then
    echo "python3 is missing: sudo apt install python3" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
    echo "Python 3.9 or newer is required (found $(python3 --version))." >&2
    exit 1
fi

missing=()
python3 -c 'import tkinter' 2>/dev/null || missing+=(python3-tk)
rm -rf "$APP_DIR/venv.new"
mkdir -p "$APP_DIR"
if ! python3 -m venv "$APP_DIR/venv.new" >/dev/null 2>&1; then
    missing+=(python3-venv)
fi
if ((${#missing[@]})); then
    echo "Installing ${missing[*]} with apt (you may be asked for your password)..."
    sudo apt-get install -y "${missing[@]}"
    python3 -c 'import tkinter'
    [[ -x "$APP_DIR/venv.new/bin/python" ]] || { rm -rf "$APP_DIR/venv.new"; python3 -m venv "$APP_DIR/venv.new"; }
fi
# Keep an existing environment (faster updates); otherwise use the one just created.
if [[ -x "$VENV/bin/python" ]]; then
    rm -rf "$APP_DIR/venv.new"
else
    rm -rf "$VENV"
    mv "$APP_DIR/venv.new" "$VENV"
fi

echo "Installing the app into $APP_DIR ..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip uninstall --quiet --yes "$APP_ID" >/dev/null 2>&1 || true
if ! "$VENV/bin/python" -m pip install --quiet "$SRC_DIR[impersonate]"; then
    echo "curl_cffi could not be installed; continuing without it."
    "$VENV/bin/python" -m pip install --quiet "$SRC_DIR"
fi

cp "$SRC_DIR/src/transcript_fetcher/assets/icon.svg" "$APP_DIR/icon.svg"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Udemy Transcript Fetcher
Comment=Save the video transcripts of your Udemy courses as text files
Exec="$VENV/bin/transcript-fetcher-gui"
Icon=$APP_DIR/icon.svg
Terminal=false
Categories=Education;
Keywords=udemy;transcript;captions;subtitles;
StartupNotify=true
StartupWMClass=$APP_ID
EOF
chmod +x "$DESKTOP_FILE"
command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP_FILE")" 2>/dev/null || true

update_dock add
echo "Done. Open 'Udemy Transcript Fetcher' from the dock or the app grid (Super key, then type 'Udemy')."
