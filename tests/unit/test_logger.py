import logging
import logging.handlers
from pathlib import Path

import pytest

from vet_soap_notetaker.logger import (
    BACKUP_COUNT,
    LOG_FILENAME,
    LOGGER_NAME,
    MAX_BYTES,
    build_logger,
    get_log_dir,
)


@pytest.fixture(autouse=True)
def clean_vet_soap_notetaker_logger():
    logger = logging.getLogger(LOGGER_NAME)
    original_handlers = list(logger.handlers)
    yield
    for handler in list(logger.handlers):
        if handler not in original_handlers:
            logger.removeHandler(handler)
            handler.close()


def test_get_log_dir_appends_logs_subdir_to_appdata_base_dir(mocker):
    mocker.patch(
        "vet_soap_notetaker.logger.get_appdata_base_dir",
        return_value=Path("/tmp/vet_soap_notetaker-base"),
    )

    assert get_log_dir() == Path("/tmp/vet_soap_notetaker-base/logs")


def test_build_logger_creates_rotating_file_handler_with_expected_settings(tmp_path):
    logger = build_logger(log_dir=tmp_path)

    handlers = [
        h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == MAX_BYTES
    assert handler.backupCount == BACKUP_COUNT
    assert Path(handler.baseFilename) == (tmp_path / LOG_FILENAME).resolve()


def test_build_logger_creates_log_directory_if_missing(tmp_path):
    log_dir = tmp_path / "nested" / "logs"

    build_logger(log_dir=log_dir)

    assert log_dir.exists()


def test_build_logger_does_not_duplicate_handlers_when_called_twice(tmp_path):
    logger1 = build_logger(log_dir=tmp_path)
    logger2 = build_logger(log_dir=tmp_path)

    assert logger1 is logger2
    handlers = [
        h for h in logger1.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(handlers) == 1


def test_build_logger_writes_info_level_messages_to_file(tmp_path):
    logger = build_logger(log_dir=tmp_path)

    logger.info("hello vet_soap_notetaker")
    for handler in logger.handlers:
        handler.flush()

    assert "hello vet_soap_notetaker" in (tmp_path / LOG_FILENAME).read_text()


def test_build_logger_defaults_to_info_level(tmp_path, monkeypatch):
    monkeypatch.delenv("VETSCRIBE_DEBUG", raising=False)

    logger = build_logger(log_dir=tmp_path)

    assert logger.level == logging.INFO


def test_build_logger_uses_debug_level_when_vet_soap_notetaker_debug_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("VETSCRIBE_DEBUG", "1")

    logger = build_logger(log_dir=tmp_path)

    assert logger.level == logging.DEBUG
