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

BUILD_ARCH=$(uname -m)
VLC_LIBRARY="/Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib"
if [ ! -f "$VLC_LIBRARY" ]; then
    echo "ERROR: VLC is installed, but $VLC_LIBRARY is missing."
    exit 1
fi

if ! file "$VLC_LIBRARY" | grep -Eq "$BUILD_ARCH|universal"; then
    echo "ERROR: The installed VLC is not compatible with this Mac ($BUILD_ARCH)."
    file "$VLC_LIBRARY"
    echo "Reinstall VLC on this Mac with: brew reinstall --cask vlc"
    exit 1
fi
echo "Architecture $BUILD_ARCH / VLC compatible - OK"

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

APP_EXECUTABLE="$APP_PATH/Contents/MacOS/IPTV Player"
if [ ! -f "$APP_EXECUTABLE" ]; then
    echo "ERROR: The app executable is missing: $APP_EXECUTABLE"
    exit 1
fi
chmod +x "$APP_EXECUTABLE"

echo "=== Signing and validating app bundle ==="
# PyInstaller signs Mach-O files while collecting them. Seal the final bundle
# as well so Gatekeeper never sees a partially/invalidly signed application.
# Use a Developer ID when supplied; otherwise produce a valid ad-hoc signature
# suitable for local/test distribution.
if [ -n "${MACOS_CODESIGN_IDENTITY:-}" ]; then
    codesign --force --deep --options runtime --timestamp \
        --entitlements "packaging/macos/entitlements.plist" \
        --sign "$MACOS_CODESIGN_IDENTITY" "$APP_PATH"
else
    codesign --force --deep --sign - "$APP_PATH"
fi

codesign --verify --deep --strict --verbose=2 "$APP_PATH"
plutil -lint "$APP_PATH/Contents/Info.plist"
file "$APP_EXECUTABLE"

APP_ARCHS=$(lipo -archs "$APP_EXECUTABLE")
if [[ " $APP_ARCHS " != *" $BUILD_ARCH "* ]]; then
    echo "ERROR: Built executable architecture '$APP_ARCHS' does not include '$BUILD_ARCH'."
    exit 1
fi

echo "=== Creating DMG ==="
rm -f "$DMG_PATH" "${DMG_PATH}.sha256"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
cp -R "$APP_PATH" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"

cat > "$DMG_ROOT/LEIA-ME.txt" <<EOF
IPTV Player para macOS ($BUILD_ARCH)

1. Arraste "IPTV Player.app" para a pasta Applications.
2. Instale o VLC em /Applications/VLC.app (https://www.videolan.org/vlc/).
3. Abra o IPTV Player.

Se o macOS bloquear esta versao nao notarizada:
  Definicoes do Sistema > Privacidade e Seguranca > Seguranca > Abrir mesmo assim

Escolha sempre o DMG correspondente ao processador do Mac:
  arm64 = Apple Silicon (M1/M2/M3/M4/M5)
  x86_64 = Intel
EOF

hdiutil create \
    -volname "IPTV Player" \
    -srcfolder "$DMG_ROOT" \
    -ov \
    -format UDZO \
    -fs HFS+ \
    "$DMG_PATH"

rm -rf "$DMG_ROOT"

if [ -n "${MACOS_CODESIGN_IDENTITY:-}" ]; then
    codesign --force --timestamp --sign "$MACOS_CODESIGN_IDENTITY" "$DMG_PATH"
fi

if [ -n "${MACOS_NOTARY_PROFILE:-}" ]; then
    if [ -z "${MACOS_CODESIGN_IDENTITY:-}" ]; then
        echo "ERROR: MACOS_NOTARY_PROFILE requires MACOS_CODESIGN_IDENTITY."
        exit 1
    fi
    echo "=== Notarizing DMG ==="
    xcrun notarytool submit "$DMG_PATH" \
        --keychain-profile "$MACOS_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG_PATH"
    xcrun stapler validate "$DMG_PATH"
fi

hdiutil verify "$DMG_PATH"
shasum -a 256 "$DMG_PATH" > "${DMG_PATH}.sha256"

APP_SIZE_MB=$(du -sm "$APP_PATH" | cut -f1)
DMG_SIZE_MB=$(du -sm "$DMG_PATH" | cut -f1)
echo "========================================"
echo "App: $APP_PATH (${APP_SIZE_MB} MB)"
echo "DMG: $DMG_PATH (${DMG_SIZE_MB} MB)"
echo "SHA-256: ${DMG_PATH}.sha256"
echo "========================================"

deactivate
