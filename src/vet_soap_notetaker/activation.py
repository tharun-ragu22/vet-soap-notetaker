"""Lets a second launch of the app ask the running one to open History.

The vet double-clicks the desktop icon while the app already sits in the tray:
``SingleInstance`` stops the second copy from starting, so before it exits it
drops a request file, and the running instance -- which polls for that file on
its Tk loop -- opens the History window. A file rather than a socket or a named
Win32 event: no port to open, nothing Windows-only, and it's testable anywhere.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("vet_soap_notetaker.activation")

ACTIVATION_FILE_NAME = "show_history.request"
POLL_INTERVAL_MS = 500


def request_activation(path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


class ActivationWatcher:
    def __init__(self, path, on_activate):
        self._path = Path(path)
        self._on_activate = on_activate

    def clear(self) -> None:
        """Drop a request left from before this instance started (e.g. a crash)."""
        self._path.unlink(missing_ok=True)

    def poll(self) -> None:
        if not self._path.exists():
            return
        self.clear()
        logger.info("another launch asked to open History")
        self._on_activate()

    def watch(self, tk_root, interval_ms: int = POLL_INTERVAL_MS) -> None:
        """Poll every ``interval_ms`` on the Tk loop, so ``on_activate`` runs on
        the main thread and may build windows directly."""

        def tick():
            try:
                self.poll()
            except Exception:
                logger.exception("opening History for another launch failed")
            tk_root.after(interval_ms, tick)

        tk_root.after(interval_ms, tick)
