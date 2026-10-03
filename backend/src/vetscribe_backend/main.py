import os
import sys
from pathlib import Path

import uvicorn

from vetscribe_backend.app import create_app
from vetscribe_backend.store import JsonFileExamStore

# Durable exam history so records survive restarts and sync across devices.
# Override the location with VETSCRIBE_EXAMS_PATH; defaults to the shared data root.
_EXAMS_PATH = Path(
    os.environ.get("VETSCRIBE_EXAMS_PATH", Path.home() / ".vetscribe" / "exams.json")
)

app = create_app(store=JsonFileExamStore(_EXAMS_PATH))


def _frozen_log_path(env=os.environ) -> Path:
    """Where the windowless frozen backend writes its logs.

    Shares the desktop app's data root: ``%APPDATA%\\VetScribe\\logs`` on Windows,
    falling back to ``~/.vetscribe/logs`` when APPDATA isn't set.
    """
    appdata = env.get("APPDATA")
    base = Path(appdata) / "VetScribe" if appdata else Path.home() / ".vetscribe"
    return base / "logs" / "backend.log"


def run():
    # A PyInstaller windowless build (console=False) has no stdout/stderr, so
    # uvicorn's default stream logging would fail. When frozen, redirect both to
    # a log file under the shared data root -- this also gives us field logs to
    # diagnose the appliance.
    if getattr(sys, "frozen", False):
        log_path = _frozen_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(log_path, "a", buffering=1, encoding="utf-8")
        sys.stdout = stream
        sys.stderr = stream
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8443")))


if __name__ == "__main__":
    run()
