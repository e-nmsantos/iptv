"""Settings dialog: the TLS opt-in is exposed and persisted."""

import pytest

from config.settings import Settings
from src.ui.dialogs import SettingsDialog


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "_get_config_dir", staticmethod(lambda: tmp_path))
    return Settings()


class TestSettingsDialogTlsOption:
    def test_checkbox_reflects_the_stored_value(self, qtbot, settings):
        settings.set("allow_insecure_tls", True)

        dialog = SettingsDialog(settings)
        qtbot.addWidget(dialog)

        assert dialog._allow_insecure_tls.isChecked() is True

    def test_checkbox_is_off_by_default(self, qtbot, settings):
        dialog = SettingsDialog(settings)
        qtbot.addWidget(dialog)

        assert dialog._allow_insecure_tls.isChecked() is False

    def test_saving_persists_the_option(self, qtbot, settings):
        dialog = SettingsDialog(settings)
        qtbot.addWidget(dialog)

        dialog._allow_insecure_tls.setChecked(True)
        dialog._save_and_accept()

        assert settings.get("allow_insecure_tls") is True
        assert Settings().get("allow_insecure_tls") is True
