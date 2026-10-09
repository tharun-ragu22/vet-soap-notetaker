"""Windows per-monitor DPI helpers for the coordinate-sensitive Win32 calls.

Calibration captures clicks in physical screen pixels (pynput reports those) and
hit-tests them with ``WindowFromPoint`` / ``GetWindowRect`` -- which interpret
coordinates in the *calling thread's* DPI awareness. Tk leaves the process
System-DPI-aware, not per-monitor, so on a monitor whose DPI differs from the
primary's, Windows virtualizes those coordinates and ``WindowFromPoint`` lands on
the wrong control -- every SOAP box can capture the same one. That's what made a
calibration done on a laptop's built-in screen (a different DPI than the docked
externals) collapse so the whole note pasted into one box.

``describe_point`` is a best-effort diagnostic for the field log (what DPI is the
monitor under this click, and what awareness is this thread running at), so a bad
capture can be explained rather than guessed at. Everything here is a no-op that
never raises off Windows (and on Windows too old for the calls), so the pure code
paths and the Linux test suite are unaffected.
"""

import contextlib
import logging
import sys

logger = logging.getLogger("vet_soap_notetaker.dpi")

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 -- a sentinel HANDLE value (not a real
# pointer) accepted by SetThreadDpiAwarenessContext on Windows 10 1703+.
_PER_MONITOR_AWARE_V2 = -4

# Names for the values GetAwarenessFromDpiAwarenessContext returns (the
# PROCESS_DPI_AWARENESS enum), for human-readable diagnostics.
_AWARENESS_NAMES = {
    0: "UNAWARE",
    1: "SYSTEM_AWARE",
    2: "PER_MONITOR_AWARE",
}


def _user32():
    """The user32 DLL on Windows, or None where ctypes.windll isn't available."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        return ctypes.windll.user32
    except Exception:
        return None


def _shcore():
    """The shcore DLL (Win8.1+) on Windows, or None where it isn't available."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        return ctypes.windll.shcore
    except Exception:
        return None


@contextlib.contextmanager
def physical_pixels():
    """Run the body with this thread in Per-Monitor-v2 DPI awareness, then restore.

    Makes WindowFromPoint / GetWindowRect report true physical pixels on every
    monitor -- matching the coordinates pynput reports -- so a calibration click
    on a monitor whose DPI differs from the primary's still hit-tests the right
    control. Scoped to the *thread*, not the process, so Tk's process-wide
    System awareness (which it uses to size its own windows) is left untouched.
    A no-op that never raises off Windows, or on Windows too old for the call.
    """
    user32 = _user32()
    previous = None
    if user32 is not None:
        try:
            previous = user32.SetThreadDpiAwarenessContext(_PER_MONITOR_AWARE_V2)
        except Exception:
            previous = None
    try:
        yield
    finally:
        if previous:
            try:
                user32.SetThreadDpiAwarenessContext(previous)
            except Exception:
                pass


def _awareness_name(code) -> str:
    return _AWARENESS_NAMES.get(code, f"code={code}")


def current_awareness() -> str:
    """This thread's DPI-awareness name, or 'unknown' where unavailable."""
    user32 = _user32()
    if user32 is None:
        return "unknown"
    try:
        ctx = user32.GetThreadDpiAwarenessContext()
        return _awareness_name(user32.GetAwarenessFromDpiAwarenessContext(ctx))
    except Exception:
        return "unknown"


def describe_point(x, y) -> str:
    """Best-effort one-liner about the monitor under (x, y): its DPI + our awareness.

    Diagnostic only, used while calibrating so a field log reveals a multi-monitor
    DPI split. Returns 'unavailable' off Windows or if any call fails (96 == 100%).
    """
    user32 = _user32()
    shcore = _shcore()
    if user32 is None or shcore is None:
        return "unavailable"
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        monitor_defaulttonearest = 2
        mdt_effective_dpi = 0
        monitor = user32.MonitorFromPoint(POINT(int(x), int(y)), monitor_defaulttonearest)
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        shcore.GetDpiForMonitor(
            monitor, mdt_effective_dpi, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
        )
        return (
            f"monitor_dpi={dpi_x.value}x{dpi_y.value} (96=100%) "
            f"thread_awareness={current_awareness()}"
        )
    except Exception:
        return "unavailable"
