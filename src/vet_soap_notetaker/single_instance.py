"""A best-effort single-instance guard backed by an OS lock on a file.

Only one process can hold the exclusive lock on the lock file at a time, so a
second copy of the desktop app (the classic case: autostart launches one at
login and the vet then double-clicks the icon) can notice that one is already
running and bow out quietly. On Windows that's what stops the second instance
from starting a second ``BackendSupervisor`` whose backend then crash-loops
fighting the first over port 8443 -- which pegs the CPU and freezes the tray.

The lock is held for the lifetime of the holding process: the OS drops it when
the process exits (even if it's killed), so a crash never leaves a stale lock
that would block the next launch. ``release`` is only needed for tests and for a
clean shutdown.
"""

import logging
import os
import sys

logger = logging.getLogger("vet_soap_notetaker.single_instance")

if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle) -> bool:
        try:
            handle.seek(0)
            # Non-blocking exclusive lock on the first byte; a second handle to
            # the same file (even in another process) fails here.
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(handle) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SingleInstance:
    def __init__(self, lock_path):
        self._lock_path = os.fspath(lock_path)
        self._handle = None

    def acquire(self) -> bool:
        """Try to become the single running instance.

        Returns True if this process now holds the lock (it's the only instance),
        False if another instance already holds it. Idempotent for the holder.
        """
        if self._handle is not None:
            return True
        os.makedirs(os.path.dirname(self._lock_path) or ".", exist_ok=True)
        handle = open(self._lock_path, "a+")
        if not _try_lock(handle):
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        except OSError:
            # Best-effort: the OS releases the lock on close / process exit anyway.
            logger.debug("failed to unlock single-instance file", exc_info=True)
        self._handle.close()
        self._handle = None
