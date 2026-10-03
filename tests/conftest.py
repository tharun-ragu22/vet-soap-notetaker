import sys
import time
import types

import pytest

from tests.tcl_env import ensure_tcl_tk_library_paths

# Correct TCL_LIBRARY / TK_LIBRARY at import time -- before pytest collects any
# test that constructs a Tk root -- so tkinter bootstraps deterministically on
# Windows instead of relying on Tk's flaky auto-search. No-op off Windows.
# See tests/tcl_env.py for the full root-cause writeup.
ensure_tcl_tk_library_paths()

if sys.platform == "win32":
    import tkinter as _tk

    _original_tk_init = _tk.Tk.__init__

    def _tk_init_with_tcl_retry(self, *args, **kwargs):
        # Even with the library paths corrected, the Windows CI runner
        # occasionally fails to read Tk's (present) script library -- init.tcl
        # or tk.tcl -- on the first try, a runner-level filesystem transient.
        # Re-assert the paths and retry briefly so a transient miss self-heals
        # instead of failing the whole suite. Covers every Tk root the tests
        # build (fixtures and MockAvimarkWindow), not just one call site.
        for attempt in range(4):
            try:
                _original_tk_init(self, *args, **kwargs)
                return
            except _tk.TclError:
                if attempt == 3:
                    raise
                ensure_tcl_tk_library_paths()
                time.sleep(0.1)

    _tk.Tk.__init__ = _tk_init_with_tcl_retry

if sys.platform != "win32":
    for _name in ("win32api", "win32con", "win32gui", "win32clipboard", "win32process", "pywintypes", "winreg"):
        if _name not in sys.modules:
            sys.modules[_name] = types.ModuleType(_name)


@pytest.fixture(autouse=True)
def _unregister_pystray_window_classes(monkeypatch):
    # pystray's win32 backend registers a real Win32 window class per Icon
    # (named after id(self)) in __init__, and only unregisters it inside the
    # mainloop's finally block -- which only runs if something calls
    # icon.run()/run_detached() and lets it exit. Every test that builds a
    # TrayApp (directly, or via build_app()) without running that loop leaks
    # its class for the rest of the process. Once CPython reuses a
    # garbage-collected Icon's address for a later Icon, RegisterClassEx
    # collides on the same class name and raises "OSError: [WinError 1410]
    # Class already exists" -- nondeterministically, depending on GC timing.
    #
    # A post-test gc.get_objects() sweep can't catch these: CPython frees an
    # Icon via refcounting the instant a test function's local variable goes
    # out of scope, well before this fixture's teardown runs, so by then the
    # object (and any way to reach its atom) is already gone. Instead, wrap
    # Icon.__init__ to record every instance *as it's constructed*, holding a
    # strong reference until teardown explicitly unregisters its class --
    # only then do we drop the reference and let it be collected normally.
    if sys.platform != "win32":
        yield
        return

    import pystray

    created = []
    original_init = pystray.Icon.__init__

    def _tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(pystray.Icon, "__init__", _tracking_init)
    yield
    for icon in created:
        atom = getattr(icon, "_atom", None)
        unregister = getattr(icon, "_unregister_class", None)
        if atom and unregister:
            try:
                unregister(atom)
            except OSError:
                pass
