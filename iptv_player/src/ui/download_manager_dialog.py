"""Download Manager dialog for viewing and controlling offline VOD downloads."""

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.downloader import VODDownloader
from .theme import Palette


class DownloadManagerDialog(QDialog):
    """Dialog showing active and completed VOD video downloads."""

    def __init__(self, media_player=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestor de Transferências VOD")
        self.resize(750, 420)
        self._player = media_player
        self._downloader = VODDownloader.get_instance()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("⬇️ Fila de Transferências Offline")
        title.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)

        folder_btn = QPushButton("📁 Abrir Pasta de Transferências")
        folder_btn.clicked.connect(self._open_download_folder)
        header_layout.addWidget(folder_btn)
        layout.addLayout(header_layout)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Título", "Progresso", "Tamanho", "Velocidade", "Estado", "Ações"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        # Connect signals
        self._downloader.progress_updated.connect(self._on_progress_updated)
        self._downloader.task_status_changed.connect(self._on_status_changed)

        # Refresh timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_table)
        self._timer.start(1000)

        self._refresh_table()

    def _open_download_folder(self):
        folder = self._downloader.download_dir
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)])
        else:
            subprocess.run(["xdg-open", str(folder)])

    @Slot()
    def _refresh_table(self):
        tasks = self._downloader.list_tasks()
        self._table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            # 0: Title
            title_item = QTableWidgetItem(task.title)
            self._table.setItem(row, 0, title_item)

            # 1: Progress
            percent = 0
            if task.total_bytes > 0:
                percent = int((task.downloaded_bytes / task.total_bytes) * 100)
            elif task.status == "completed":
                percent = 100
            pbar = QProgressBar()
            pbar.setValue(percent)
            pbar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pbar.setStyleSheet("max-height: 16px; font-size: 10px;")
            self._table.setCellWidget(row, 1, pbar)

            # 2: Size
            downloaded_mb = task.downloaded_bytes / (1024 * 1024)
            total_mb = task.total_bytes / (1024 * 1024) if task.total_bytes > 0 else 0
            size_str = f"{downloaded_mb:.1f} MB / {total_mb:.1f} MB" if total_mb > 0 else f"{downloaded_mb:.1f} MB"
            self._table.setItem(row, 2, QTableWidgetItem(size_str))

            # 3: Speed
            speed_mbps = (task.speed_bps * 8) / (1024 * 1024)
            speed_str = f"{speed_mbps:.1f} Mbps" if task.status == "downloading" and speed_mbps > 0 else "-"
            self._table.setItem(row, 3, QTableWidgetItem(speed_str))

            # 4: Status
            status_map = {
                "pending": "A aguardar...",
                "downloading": "A transferir",
                "paused": "Pausado",
                "completed": "Concluído ✅",
                "error": "Erro ⚠️",
                "cancelled": "Cancelado",
            }
            status_str = status_map.get(task.status, task.status)
            self._table.setItem(row, 4, QTableWidgetItem(status_str))

            # 5: Actions
            actions_widget = QWidget()
            act_layout = QHBoxLayout(actions_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(4)

            if task.status == "downloading":
                pause_btn = QPushButton("⏸️")
                pause_btn.setToolTip("Pausar")
                pause_btn.clicked.connect(lambda _, tid=task.task_id: self._downloader.pause_download(tid))
                act_layout.addWidget(pause_btn)
            elif task.status in ("paused", "error"):
                resume_btn = QPushButton("▶️")
                resume_btn.setToolTip("Retomar")
                resume_btn.clicked.connect(lambda _, tid=task.task_id: self._downloader.resume_download(tid))
                act_layout.addWidget(resume_btn)

            if task.status == "completed" and self._player:
                play_btn = QPushButton("▶️ Ver")
                play_btn.setToolTip("Reproduzir ficheiro local")
                play_btn.clicked.connect(lambda _, p=task.target_path: self._play_local_file(p))
                act_layout.addWidget(play_btn)

            cancel_btn = QPushButton("❌")
            cancel_btn.setToolTip("Cancelar / Eliminar")
            cancel_btn.clicked.connect(lambda _, tid=task.task_id: self._downloader.cancel_download(tid))
            act_layout.addWidget(cancel_btn)

            self._table.setCellWidget(row, 5, actions_widget)

    def _play_local_file(self, path: Path):
        if path.exists() and self._player:
            self._player.play(str(path), is_live=False)
            self.accept()

    @Slot(str, int, int, float)
    def _on_progress_updated(self, task_id: str, downloaded: int, total: int, speed: float):
        # Trigger periodic fast update
        pass

    @Slot(str, str)
    def _on_status_changed(self, task_id: str, status: str):
        self._refresh_table()

