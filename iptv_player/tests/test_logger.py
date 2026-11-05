"""Tests for logging setup, module-logger routing and credential redaction."""

import logging
import logging.handlers

import pytest

from src.utils import logger as logger_module
from src.utils.logger import get_logger, redact_sensitive, setup_logger

_APP_LOGGER = "iptv_player"


@pytest.fixture
def clean_logging():
    """Snapshot and restore logging state around a test."""
    root = logging.getLogger()
    app_logger = logging.getLogger(_APP_LOGGER)
    saved_root = (list(root.handlers), root.level)
    saved_app = list(app_logger.handlers)

    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
    for logger in (root, app_logger):
        if hasattr(logger, logger_module._CONFIGURED_ATTR):
            delattr(logger, logger_module._CONFIGURED_ATTR)

    yield

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_root[0]:
        root.addHandler(handler)
    root.setLevel(saved_root[1])

    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
    for handler in saved_app:
        app_logger.addHandler(handler)

    for logger in (root, app_logger):
        if hasattr(logger, logger_module._CONFIGURED_ATTR):
            delattr(logger, logger_module._CONFIGURED_ATTR)


class TestRedaction:
    @pytest.mark.parametrize(
        "raw",
        [
            "http://host/api?username=joao&password=segredo",
            "http://host/api?token=abc123",
            "http://host/api?auth=xyz",
            "http://host/portal.php?mac=00:1A:2B:3C:4D:5E",
        ],
    )
    def test_hides_query_secrets(self, raw):
        redacted = redact_sensitive(raw)

        assert "segredo" not in redacted
        assert "abc123" not in redacted
        assert "xyz" not in redacted

    def test_hides_xtream_path_credentials(self):
        redacted = redact_sensitive("http://host/live/joao/segredo/1234.ts")

        assert "joao" not in redacted
        assert "segredo" not in redacted
        assert redacted == "http://host/live/***/***/1234.ts"

    def test_hides_mac_addresses(self):
        assert redact_sensitive("MAC 00:1a:2b:3c:4d:5e") == "MAC **:**:**:**:**:**"

    def test_keeps_innocent_text(self):
        assert redact_sensitive("A ligar ao canal 12") == "A ligar ao canal 12"


class TestSetupLogger:
    def test_installs_root_handlers_once(self, clean_logging):
        root = logging.getLogger()
        before = list(root.handlers)

        setup_logger()
        setup_logger()
        setup_logger("outro")

        added = [handler for handler in root.handlers if handler not in before]
        assert len(added) == 2
        assert any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in added)
        assert root.level == logging.DEBUG

    def test_module_loggers_reach_the_handlers(self, clean_logging):
        setup_logger()

        module_logger = logging.getLogger("src.core.cast_manager")

        assert module_logger.hasHandlers()
        assert module_logger.getEffectiveLevel() == logging.DEBUG

    def test_noisy_third_party_loggers_are_quietened(self, clean_logging):
        setup_logger()

        for name in ("urllib3", "requests", "pychromecast"):
            assert logging.getLogger(name).level == logging.WARNING

    def test_module_records_are_written_and_redacted(self, clean_logging, monkeypatch, tmp_path):
        log_file = tmp_path / "iptv_player.log"
        monkeypatch.setattr(logger_module, "log_file_path", lambda: log_file)

        setup_logger()
        logging.getLogger("src.core.cast_manager").warning(
            "Falha em http://host/live/joao/segredo/1234.ts?password=segredo"
        )
        for handler in logging.getLogger().handlers:
            handler.flush()

        content = log_file.read_text(encoding="utf-8")
        assert "src.core.cast_manager" in content
        assert "segredo" not in content
        assert "joao" not in content

    def test_get_logger_configures_the_app_logger(self, clean_logging):
        logger = get_logger()

        assert logger.name == _APP_LOGGER
        assert logging.getLogger().handlers

    def test_get_logger_is_idempotent(self, clean_logging):
        root = logging.getLogger()
        before = list(root.handlers)

        get_logger()
        get_logger("iptv_player")

        added = [handler for handler in root.handlers if handler not in before]
        assert len(added) == 2
