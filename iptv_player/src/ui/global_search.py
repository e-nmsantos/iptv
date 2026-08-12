"""Global search dialog for every saved IPTV catalogue."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class GlobalSearchDialog(QDialog):
    def __init__(self, search_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pesquisa global")
        self.resize(720, 520)
        self._search_callback = search_callback
        self.selected_result = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pesquisar em Live, VOD e Séries de todas as playlists"))
        self._query = QLineEdit()
        self._query.setPlaceholderText("Escreve pelo menos dois caracteres…")
        layout.addWidget(self._query)
        self._status = QLabel("0 resultados")
        layout.addWidget(self._status)
        self._results = QListWidget()
        self._results.itemActivated.connect(self._activate)
        layout.addWidget(self._results, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._run_search)
        self._query.textChanged.connect(self._timer.start)
        self._query.setFocus()

    def _run_search(self):
        self._results.clear()
        query = self._query.text().strip()
        if len(query) < 2:
            self._status.setText("Escreve pelo menos dois caracteres")
            return
        results = self._search_callback(query)
        for result in results:
            channel = result["channel"]
            kind = {
                "live": "LIVE",
                "vod": "VOD",
                "movie": "VOD",
                "series": "SÉRIE",
            }.get(channel.stream_type, channel.stream_type.upper())
            item = QListWidgetItem(
                f"[{kind}] {channel.name}  ·  {result['playlist_name']}  ·  {channel.group}"
            )
            item.setData(Qt.ItemDataRole.UserRole, result)
            self._results.addItem(item)
        self._status.setText(f"{len(results)} resultado(s)")

    def _activate(self, item: QListWidgetItem):
        self.selected_result = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
