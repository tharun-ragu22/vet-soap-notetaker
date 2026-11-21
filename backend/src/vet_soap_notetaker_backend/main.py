import io
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import uvicorn

from vet_soap_notetaker_backend.app import create_app
from vet_soap_notetaker_backend.store import JsonFileExamStore

# Durable exam history so records survive restarts and sync across devices.
# Override the location with VETSCRIBE_EXAMS_PATH; defaults to the shared data root.
# The data dir keeps its legacy "VetScribe"/".vetscribe" name (see paths.py) so the
# rename to Vet Soap Notetaker doesn't orphan existing installs' data.
_EXAMS_PATH = Path(
    os.environ.get("VETSCRIBE_EXAMS_PATH", Path.home() / ".vetscribe" / "exams.json")
)

# Uploads sent with Prefer: respond-async wait here until processed, so a
# restart resumes them instead of losing the recording.
_INCOMING_AUDIO_DIR = _EXAMS_PATH.parent / "incoming"

app = create_app(store=JsonFileExamStore(_EXAMS_PATH), audio_dir=_INCOMING_AUDIO_DIR)


def _frozen_log_path(env=os.environ) -> Path:
    """Where the windowless frozen backend writes its logs.

    Shares the desktop app's data root: ``%APPDATA%\\VetScribe\\logs`` on Windows,
    falling back to ``~/.vetscribe/logs`` when APPDATA isn't set.
    """
    appdata = env.get("APPDATA")
    base = Path(appdata) / "VetScribe" if appdata else Path.home() / ".vetscribe"
    return base / "logs" / "backend.log"


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# Same cap as the desktop's log: 5 MB x 3 backups.
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


class _LineLogger(io.TextIOBase):
    """Stands in for sys.stdout/stderr in the windowless exe: each line written
    (a stray print, a traceback) goes through ``logger``, so it lands in the
    rotating log rather than on a file handle that rotation would leave behind."""

    def __init__(self, logger: logging.Logger, level: int):
        self._logger = logger
        self._level = level
        self._pending = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        *lines, self._pending = (self._pending + text).split("\n")
        for line in lines:
            if line.strip():
                self._logger.log(self._level, line)
        return len(text)

    def flush(self) -> None:
        if self._pending.strip():
            self._logger.log(self._level, self._pending)
        self._pending = ""


def _log_to_rotating_file(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    # uvicorn runs with log_config=None here, so its loggers propagate to the
    # root handler; keep their INFO lines (startup, access log) as before.
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # A failed log write reports itself on stderr -- which is now the log, so
    # it would recurse. With no console to report to, stay silent instead.
    logging.raiseExceptions = False
    stdio = logging.getLogger("vet_soap_notetaker_backend.stdio")
    sys.stdout = _LineLogger(stdio, logging.INFO)
    sys.stderr = _LineLogger(stdio, logging.ERROR)


def _show_backend_logs(console: bool = True) -> None:
    # uvicorn configures only its own loggers, so the backend's INFO lines
    # (per-recording timings, provider retries) would otherwise be dropped.
    package_logger = logging.getLogger("vet_soap_notetaker_backend")
    package_logger.setLevel(logging.INFO)
    if console and not package_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        package_logger.addHandler(handler)


def run():
    # A PyInstaller windowless build (console=False) has no stdout/stderr, so
    # uvicorn's default stream logging would fail. When frozen, everything goes
    # to a rotating log file under the shared data root -- the field logs used
    # to diagnose the appliance.
    frozen = getattr(sys, "frozen", False)
    run_options = {}
    if frozen:
        _log_to_rotating_file(_frozen_log_path())
        run_options["log_config"] = None
    _show_backend_logs(console=not frozen)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8443")), **run_options)


if __name__ == "__main__":
    run()
