import logging
import logging.handlers
import os
from pathlib import Path

from vet_soap_notetaker.paths import get_appdata_base_dir

LOGGER_NAME = "vet_soap_notetaker"
LOG_FILENAME = "vet_soap_notetaker.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def get_log_dir() -> Path:
    return get_appdata_base_dir() / "logs"


def build_logger(log_dir=None, level=None):
    log_dir = Path(log_dir) if log_dir else get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    if level is None:
        level = logging.DEBUG if os.environ.get("VETSCRIBE_DEBUG") else logging.INFO

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    has_file_handler = any(
        isinstance(handler, logging.handlers.RotatingFileHandler)
        for handler in logger.handlers
    )
    if not has_file_handler:
        handler = logging.handlers.RotatingFileHandler(
            log_dir / LOG_FILENAME, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    has_console_handler = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.handlers.RotatingFileHandler)
        for handler in logger.handlers
    )
    if not has_console_handler:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
