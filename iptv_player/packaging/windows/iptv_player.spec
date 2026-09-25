# -*- mode: python ; coding: utf-8 -*-

import os

project_root = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))

analysis = Analysis(
    [os.path.join(project_root, "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=[
        "vlc",
        "Crypto.Cipher.AES",
        "keyring.backends.Windows",
        "requests",
        "urllib.parse",
        "PySide6.QtCore",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "src.core.channel_cleaner",
        "src.core.metadata_enricher",
        "src.core.server_speedtest",
        "src.core.subtitles_finder",
        "src.core.cast_manager",
        "src.core.downloader",
        "src.core.playlist_health",
        "src.player.radio_sync",
        "src.player.pvr_recorder",
        "src.ui.pip_window",
        "src.ui.multiview_widget",
        "src.ui.multi_view_dialog",
        "src.ui.download_manager_dialog",
        "src.ui.cast_dialog",
        "src.ui.epg_grid_widget",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="IPTVPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="IPTVPlayer",
)
