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

from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.main_window import MainWindow
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

    # Create and show main window
    try:
        window = MainWindow()
    except RuntimeError as exc:
        logger.exception("Failed to initialize secure application storage")
        QMessageBox.critical(
            None,
            "Erro no armazenamento seguro",
            str(exc),
        )
        return 1
    window.show()

    logger.info("IPTV Player started successfully")

    # Run event loop
    return app.exec()


if __name__ == "__main__":
    sys.excepthook = global_exception_hook
    sys.exit(main())
