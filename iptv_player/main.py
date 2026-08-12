#!/usr/bin/env python3
"""IPTV Player - Main Entry Point.

A feature-rich IPTV player supporting M3U, M3U8, M3U_Plus, Xtream Codes API,
and Stalker Portal (MAC) formats.

Usage:
    python main.py
    
Requirements:
    pip install -r requirements.txt
"""

import os
import sys

# Ensure the parent directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.theme import build_stylesheet
from src.utils.logger import setup_logger

logger = setup_logger()


def global_exception_hook(exctype, value, traceback):
    """Catch all unhandled exceptions, log them, and show a user-friendly dialog."""
    import traceback as tb

    logger.critical("Unhandled exception caught:", exc_info=(exctype, value, traceback))

    error_msg = "".join(tb.format_exception(exctype, value, traceback))
    details = (
        "Ocorreu um erro inesperado e a aplicação precisa de fechar.\n\n"
        f"Por favor, reporte este erro.\n\nDetalhes:\n{error_msg}"
    )
    QMessageBox.critical(None, "Erro Crítico da Aplicação", details)
    sys.exit(1)


def main():
    """Initialize and run the IPTV Player application."""
    # Setup logging
    logger.info("IPTV Player starting...")

    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("IPTV Player")
    app.setOrganizationName("IPTVPlayer")
    app.setOrganizationDomain("iptvplayer.local")

    # Set application-wide attributes
    app.setStyle("Fusion")  # Consistent cross-platform look
    app.setStyleSheet(build_stylesheet())

    # Import the main window only after QApplication exists. On macOS,
    # python-vlc loads libvlc while the module is imported; doing this here
    # lets us show a useful error instead of Finder reporting only that the
    # application could not be opened.
    try:
        from src.ui.main_window import MainWindow
    except (ImportError, OSError) as exc:
        logger.exception("Failed to load application runtime")
        detail = str(exc)
        if "vlc" in detail.lower():
            message = (
                "Não foi possível carregar o VLC.\n\n"
                "Instala a versão do VLC compatível com o processador deste Mac "
                "em /Applications/VLC.app e volta a abrir o IPTV Player.\n\n"
                "Download: https://www.videolan.org/vlc/"
            )
        else:
            message = f"Não foi possível carregar os componentes da aplicação.\n\n{detail}"
        QMessageBox.critical(None, "Erro ao iniciar o IPTV Player", message)
        return 1

    # Create and show main window
    try:
        window = MainWindow()
    except RuntimeError as exc:
        logger.exception("Failed to initialize application")
        QMessageBox.critical(
            None,
            "Erro ao iniciar o IPTV Player",
            str(exc),
        )
        return 1
    window.show()

    logger.info("IPTV Player started successfully")

    # Used by the macOS packaging workflow to prove that the frozen bundle
    # reaches a functioning Qt event loop. Normal launches are unaffected.
    if os.environ.get("IPTV_PLAYER_SMOKE_TEST") == "1":
        QTimer.singleShot(3000, app.quit)

    # Run event loop
    return app.exec()


if __name__ == "__main__":
    sys.excepthook = global_exception_hook
    sys.exit(main())
