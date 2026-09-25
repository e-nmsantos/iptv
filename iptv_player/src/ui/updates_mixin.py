"""Update checks, installer download and diagnostics reporting.

Extracted from ``main_window.py``. ``UpdatesMixin`` must be mixed into a class
that provides ``_settings``, ``_db``, ``_logger``, ``_run_background``,
``_closing`` and the standard ``QMainWindow`` accessors.
"""

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from config import APP_VERSION

from ..core.app_diagnostics import build_diagnostics_report
from ..core.update_manager import (
    download_artifact,
    fetch_manifest,
    is_newer_version,
    select_artifact,
)
from ..utils.logger import log_file_path


class UpdatesMixin:
    """Update checks, installer download/launch, diagnostics and onboarding."""

    def _check_for_updates(self):
        """Check the configured manifest for a newer release (manual)."""
        url = (self._settings.get("update_manifest_url") or "").strip()
        if not url:
            QMessageBox.information(
                self,
                "Atualizações",
                "Não foi configurado um repositório de atualizações.\n"
                "Define o URL do manifesto em Definições → Rede → "
                "URL do manifesto de atualizações.",
            )
            return

        def fetch():
            return fetch_manifest(url, timeout=15)

        def show(info):
            if is_newer_version(info.version, APP_VERSION):
                self._offer_update(info)
            else:
                QMessageBox.information(
                    self,
                    "Atualizações",
                    f"Estás a usar a versão mais recente ({APP_VERSION}).",
                )

        def fail(message):
            QMessageBox.warning(
                self, "Atualizações", f"Não foi possível verificar: {message}"
            )

        self._run_background(
            fetch, show, fail, status_message="A verificar atualizações..."
        )

    @Slot()
    def _auto_check_updates(self):
        """Silently check for updates at most once per day."""
        url = (self._settings.get("update_manifest_url") or "").strip()
        if not url:
            return
        now = int(time.time())
        if now - int(self._settings.get("last_update_check_ts", 0)) < 24 * 3600:
            return
        self._settings.set("last_update_check_ts", now)

        def fetch():
            return fetch_manifest(url, timeout=15)

        def show(info):
            if is_newer_version(info.version, APP_VERSION):
                self._offer_update(info)

        def fail(message):
            self._logger.debug(f"Auto-update check failed: {message}")

        self._run_background(fetch, show, fail)

    def _offer_update(self, info):
        """Prompt the user to download and install a newer release."""
        artifact = select_artifact(info)
        if artifact is None:
            QMessageBox.information(
                self,
                "Atualização disponível",
                f"Está disponível a versão {info.version}, mas não existe um "
                "instalador para este sistema.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Atualização disponível",
            f"Está disponível a versão {info.version} (atual: {APP_VERSION}).\n\n"
            f"Descarregar e instalar {artifact.filename}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._download_and_install(artifact)

    def _download_and_install(self, artifact):
        """Download, verify and launch a release artifact."""
        dest_dir = Path(tempfile.gettempdir()) / "iptv-player-updates"

        def run():
            return download_artifact(artifact, dest_dir)

        def done(path):
            self._launch_installer(path)

        def fail(message):
            QMessageBox.warning(
                self, "Atualização", f"Não foi possível descarregar: {message}"
            )

        self._run_background(
            run,
            done,
            fail,
            status_message=f"A descarregar {artifact.filename}...",
        )

    def _launch_installer(self, path: Path):
        """Open the downloaded installer/DMG and close the running app."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                QMessageBox.information(
                    self,
                    "Atualização",
                    f"Descarregado em:\n{path}",
                )
                return
            self._closing = True
            QTimer.singleShot(0, self.close)
        except Exception as exc:
            self._logger.error(f"Failed to launch installer: {exc}")
            QMessageBox.warning(
                self,
                "Atualização",
                f"Não foi possível abrir o instalador: {exc}",
            )

    @Slot()
    def _export_diagnostics_report(self):
        """Write a credential-free diagnostics report to a user-chosen file."""
        default_name = f"iptv-player-diagnostico-{datetime.now():%Y%m%d-%H%M%S}.txt"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar relatório de diagnóstico",
            str(Path.home() / default_name),
            "Ficheiro de texto (*.txt)",
        )
        if not target:
            return
        try:
            report = build_diagnostics_report(
                self._db._db_path,
                self._settings,
                log_file_path(),
                APP_VERSION,
            )
            Path(target).write_text(report, encoding="utf-8")
            QMessageBox.information(
                self,
                "Relatório guardado",
                f"Relatório de diagnóstico guardado em:\n{target}",
            )
        except Exception as exc:
            self._logger.error(f"Failed to export diagnostics report: {exc}")
            QMessageBox.warning(
                self,
                "Erro",
                f"Não foi possível guardar o relatório: {exc}",
            )

    @Slot()
    def _show_first_run_welcome(self):
        """Show a short onboarding hint the first time the app is launched."""
        if self._settings.get("first_run_done", False):
            return
        self._settings.set("first_run_done", True)
        QMessageBox.information(
            self,
            "Bem-vindo ao IPTV Player",
            "Para começar, importa uma lista:\n\n"
            "• M3U / M3U8 — Ficheiro → Importar M3U (Ctrl+M)\n"
            "• Xtream Codes — Ficheiro → Adicionar Xtream (Ctrl+X)\n"
            "• Stalker Portal — Ficheiro → Adicionar Stalker (Ctrl+Shift+S)\n\n"
            "As tuas credenciais são guardadas cifradas no sistema.",
        )
