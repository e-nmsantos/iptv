#!/bin/bash
# Build IPTV Player.app and a distributable DMG.
# Run this on macOS from the project root:
#   bash packaging/macos/build.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Checking prerequisites ==="

if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: This build script must be run on macOS."
    exit 1
fi

# VLC is intentionally external. python-vlc discovers its native library and
# plugins in /Applications/VLC.app both while building and at runtime.
if [ ! -d "/Applications/VLC.app" ]; then
    echo "ERROR: VLC.app was not found in /Applications."
    echo "Install it with: brew install --cask vlc"
    echo "Or download it from: https://videolan.org/vlc/"
    exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
    echo "ERROR: Xcode Command Line Tools were not found."
    echo "Install them with: xcode-select --install"
    exit 1
fi

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: python3 was not found."
    exit 1
fi

PYVER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))'; then
    echo "ERROR: Python 3.9+ is required; found $PYVER."
    exit 1
fi
echo "Python $PYVER - OK"

echo "=== Setting up build environment ==="
"$PYTHON" -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller Pillow

ICON_PATH="packaging/macos/icon.icns"
if [ ! -f "$ICON_PATH" ]; then
    echo "=== Generating app icon ==="
    python packaging/macos/generate_icon.py
    if [ ! -f "$ICON_PATH" ]; then
        echo "WARNING: icon.icns was not generated; the generic icon will be used."
    fi
fi

echo "=== Building app bundle ==="
rm -rf build dist
pyinstaller --noconfirm packaging/macos/iptv_player.spec

APP_PATH="dist/IPTV Player.app"
DMG_PATH="dist/IPTV Player.dmg"
DMG_ROOT="dist/dmg-root"

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: $APP_PATH was not created."
    exit 1
fi

echo "=== Creating DMG ==="
rm -f "$DMG_PATH" "${DMG_PATH}.sha256"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
cp -R "$APP_PATH" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"

hdiutil create \
    -volname "IPTV Player" \
    -srcfolder "$DMG_ROOT" \
    -ov \
    -format UDZO \
    -fs APFS \
    "$DMG_PATH"

rm -rf "$DMG_ROOT"
shasum -a 256 "$DMG_PATH" > "${DMG_PATH}.sha256"

APP_SIZE_MB=$(du -sm "$APP_PATH" | cut -f1)
DMG_SIZE_MB=$(du -sm "$DMG_PATH" | cut -f1)
echo "========================================"
echo "App: $APP_PATH (${APP_SIZE_MB} MB)"
echo "DMG: $DMG_PATH (${DMG_SIZE_MB} MB)"
echo "SHA-256: ${DMG_PATH}.sha256"
echo "========================================"

deactivate
