# PyInstaller spec for building the macOS .app bundle.
# Must be run on macOS: `pyinstaller packaging/macos/iptv_player.spec` from the project root.
import os

block_cipher = None
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))
ICON_PATH = os.path.join(PROJECT_ROOT, "packaging", "macos", "icon.icns")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Core media player
        "vlc",

        # HTTP / network
        "requests",
        "aiohttp",

        # Cryptography (Stalker Portal)
        "Crypto",
        "Crypto.Cipher",
        "Crypto.Cipher.AES",
        "Crypto.Util",
        "Crypto.Util.Padding",
        "Crypto.Util.py3compat",
        "Crypto.Util.number",
        "Crypto.Hash",
        "Crypto.Protocol",

        # Keyring — all backends for cross-platform
        "keyring",
        "keyring.backends.macOS",
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
        "keyring.backends.Windows",
        "keyring.backends.chainer",
        "keyring.core",

        # PySide6 — all submodules used across UI files
        "PySide6",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",

        # XML / EPG parsing
        "lxml",
        "m3u8",

        # Async I/O
        "aiofiles",

        # Validation
        "validators",

        # All project modules (safety net for PyInstaller tree traversal)
        "config",
        "config.settings",
        "src",
        "src.core",
        "src.core.channel",
        "src.core.playlist",
        "src.core.epg",
        "src.core.database",
        "src.core.secrets",
        "src.core.epg_loader",
        "src.parsers",
        "src.parsers.m3u_parser",
        "src.parsers.xtream_parser",
        "src.parsers.stalker_parser",
        "src.player",
        "src.player.media_player",
        "src.ui",
        "src.ui.main_window",
        "src.ui.playlist_widget",
        "src.ui.channel_list",
        "src.ui.player_widget",
        "src.ui.epg_widget",
        "src.ui.pill_tabs",
        "src.ui.series_browser",
        "src.ui.dialogs",
        "src.utils",
        "src.utils.helpers",
        "src.utils.logger",
    ],
    hookspath=[],
    runtime_hooks=[os.path.join(PROJECT_ROOT, "packaging", "macos", "runtime_hook_keyring.py")],
    excludes=[
        # Exclude tkinter (not used, avoids bundling Tcl/Tk)
        "tkinter",
        "tkinter.*",
        "_tkinter",
        # Exclude test packages
        "unittest",
        "pytest",
        # Exclude matplotlib if not used
        "matplotlib",
        "PIL",
        "numpy",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IPTV Player",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="IPTV Player",
)

app = BUNDLE(
    coll,
    name="IPTV Player.app",
    icon=ICON_PATH if os.path.isfile(ICON_PATH) else None,
    bundle_identifier="local.iptvplayer.app",
    info_plist={
        "CFBundleName": "IPTV Player",
        "CFBundleDisplayName": "IPTV Player",
        "CFBundleIdentifier": "local.iptvplayer.app",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "CFBundleExecutable": "IPTV Player",
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "IPTV Player © 2025",
        "LSApplicationCategoryType": "public.app-category.entertainment",
        "NSRequiresAquaSystemAppearance": False,
    },
)
