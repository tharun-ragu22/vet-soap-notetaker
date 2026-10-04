import logging
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger("vet_soap_notetaker.backend_supervisor")

# The bundled backend executable's name and the subfolder the installer drops it
# in, relative to the desktop app's own executable. Both halves ship as separate
# PyInstaller --onedir builds; the installer places the backend under
# <install>\backend\ next to Vet Soap Notetaker.exe.
BACKEND_SUBDIR = "backend"
BACKEND_EXE_NAME = "VetSoapNotetakerBackend.exe"

# Windows flag to launch the backend without flashing up a console window -- the
# clinic PC runs it as a silent appliance, so the vet never sees it. 0 elsewhere.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_bundled_backend() -> Path | None:
    """Locate the packaged backend executable shipped beside the frozen app.

    Returns the path only when we're a PyInstaller-frozen build *and* the backend
    exe is actually present next to us. In a dev checkout (not frozen) this
    returns None, so the supervisor stays off and leaves the separately-run
    backend (``setup.ps1`` / ``uv run``) alone.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / BACKEND_SUBDIR / BACKEND_EXE_NAME
    return candidate if candidate.exists() else None


def default_backend_launch(exe_path):
    """Build the launch callable the supervisor uses to start the backend.

    Returns a zero-arg callable that spawns the backend exe windowless and hands
    back the ``Popen`` handle. Kept separate from the exe-discovery so tests can
    inject their own launcher.
    """
    exe_path = Path(exe_path)

    def _launch():
        return subprocess.Popen([str(exe_path)], creationflags=_CREATE_NO_WINDOW)

    return _launch


class BackendSupervisor:
    """Keeps the bundled backend process alive while the desktop app runs.

    On the clinic PC the backend and desktop app run together as a headless
    appliance; keeping the backend up is the desktop app's job. On ``start`` it
    launches the backend as a hidden child process and, on a daemon polling
    thread, relaunches it if it ever exits -- so a crash or transient failure
    self-heals with nobody touching the PC, and a single autostart entry (the
    desktop app) brings the whole stack back after a reboot.

    Mirrors ``OfflineQueue`` / ``InjectionPoller``: a daemon thread polls on an
    interval and the handle is stopped from ``TrayApp.quit()``. ``launch`` is
    injected (``default_backend_launch`` in production) so the logic is testable
    without a real backend exe. A dev checkout passes ``launch=None`` (no bundled
    exe) and the supervisor does nothing.
    """

    def __init__(self, launch, poll_interval_seconds=5):
        self.launch = launch
        self.poll_interval_seconds = poll_interval_seconds
        self._process = None
        self._stop_event = threading.Event()
        self._thread = None

    def _spawn(self):
        try:
            self._process = self.launch()
            logger.info("backend process started")
        except Exception:
            # A failed launch must not take the desktop app down; the next poll
            # retries. (e.g. the exe was moved, or AV quarantined it.)
            logger.exception("failed to start the backend process")
            self._process = None

    def process_once(self):
        """Ensure the backend is running; (re)launch it if it has exited."""
        if self._process is not None and self._process.poll() is None:
            return  # still alive
        if self._process is not None:
            logger.warning(
                "backend process exited (code %s); restarting",
                self._process.returncode,
            )
        self._spawn()

    def start(self):
        if self.launch is None:
            logger.info("no bundled backend found; supervisor disabled (dev run?)")
            return
        self._stop_event.clear()
        self.process_once()  # bring it up immediately, don't wait a full interval
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(self.poll_interval_seconds):
            self.process_once()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._process is not None and self._process.poll() is None:
            logger.info("stopping the backend process")
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                # Didn't die politely -- force it so we don't leave an orphan.
                try:
                    self._process.kill()
                except Exception:
                    logger.exception("failed to kill the backend process")
