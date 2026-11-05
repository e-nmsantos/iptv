"""Global search dialog: debounce, result formatting and selection."""

from src.core.channel import Channel
from src.ui.global_search import GlobalSearchDialog


def _result(name="Canal", stream_type="live", playlist="Lista"):
    return {
        "channel": Channel(name=name, url="http://h/1.ts", stream_type=stream_type, group="Notícias"),
        "playlist_name": playlist,
    }


class TestSearchDialog:
    def test_short_queries_ask_for_more_characters(self, qtbot):
        calls = []
        dialog = GlobalSearchDialog(lambda query: calls.append(query) or [])
        qtbot.addWidget(dialog)

        dialog._query.setText("a")
        dialog._run_search()

        assert dialog._status.text() == "Escreve pelo menos dois caracteres"
        assert dialog._results.count() == 0
        assert calls == []

    def test_results_are_listed_with_the_content_kind(self, qtbot):
        results = [
            _result("Canal Um", "live"),
            _result("Filme", "movie"),
            _result("Série", "series"),
        ]
        dialog = GlobalSearchDialog(lambda query: results)
        qtbot.addWidget(dialog)

        dialog._query.setText("ca")
        dialog._run_search()

        assert dialog._results.count() == 3
        assert dialog._results.item(0).text().startswith("[LIVE] Canal Um")
        assert dialog._results.item(1).text().startswith("[VOD] Filme")
        assert dialog._results.item(2).text().startswith("[SÉRIE] Série")
        assert "Lista" in dialog._results.item(0).text()
        assert dialog._status.text() == "3 resultado(s)"

    def test_empty_results_update_the_status(self, qtbot):
        dialog = GlobalSearchDialog(lambda query: [])
        qtbot.addWidget(dialog)

        dialog._query.setText("zz")
        dialog._run_search()

        assert dialog._results.count() == 0
        assert dialog._status.text() == "0 resultado(s)"

    def test_activating_a_result_stores_it_and_closes(self, qtbot):
        result = _result("Canal Um")
        dialog = GlobalSearchDialog(lambda query: [result])
        qtbot.addWidget(dialog)
        dialog._query.setText("ca")
        dialog._run_search()

        dialog._activate(dialog._results.item(0))

        assert dialog.selected_result == result
        assert dialog.result() == int(dialog.DialogCode.Accepted)

    def test_typing_starts_the_debounce_timer(self, qtbot):
        dialog = GlobalSearchDialog(lambda query: [])
        qtbot.addWidget(dialog)

        dialog._query.setText("ca")

        assert dialog._timer.isActive()
