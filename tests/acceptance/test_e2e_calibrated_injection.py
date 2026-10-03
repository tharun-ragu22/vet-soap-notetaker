"""End-to-end calibrated injection against native-Win32 mock AVImark windows.

This is the acceptance test the Tkinter mock could never provide: it uses real
native EDIT/checkbox controls (see mock_avimark_soap.py), so it exercises
calibration's *actual* control-id resolution -- capture each box, re-find it, and
paste each SOAP section into its own box -- across several layouts, including one
with unlabeled controls that forces the position fallback.

Windows-only (needs real Win32 controls); auto-skips elsewhere and runs for real on
the windows-latest CI runner.
"""

import sys
import threading
import time

import pytest

if sys.platform != "win32":
    pytest.skip("requires a real Windows GUI environment", allow_module_level=True)

from vetscribe.avimark_injector import AvimarkInjector
from tests.acceptance.mock_avimark_soap import (
    SAMPLE_NOTE,
    MockAvimarkSoapApp,
    calibrate_and_inject,
)


class _MockOnThread:
    """Run a mock SOAP window + its message pump on a background thread.

    The window must pump on its own thread so that (a) the synthetic paste
    keystrokes it receives get dispatched, and (b) cross-thread focus
    (AttachThreadInput + SetFocus) -- the real injection path -- is valid.
    """

    def __init__(self, layout):
        self.layout = layout
        self.app = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        self.app = MockAvimarkSoapApp(layout=self.layout)
        self._ready.set()
        self.app.mainloop()

    def __enter__(self):
        self._thread.start()
        assert self._ready.wait(timeout=10), "mock window did not come up"
        time.sleep(0.5)  # let it paint and reach the foreground
        return self.app

    def __exit__(self, *exc):
        if self.app is not None:
            self.app.close()
        self._thread.join(timeout=5)


def _wait_for_fill(app, section, expected, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if expected in app.box_text(section):
            return app.box_text(section)
        time.sleep(0.1)
    return app.box_text(section)


@pytest.mark.parametrize("layout", [1, 2, 3, 4, 5])
def test_calibrated_injection_routes_each_section_to_its_box(layout):
    with _MockOnThread(layout) as app:
        injector = AvimarkInjector(title_marker="AVImark")

        calibrate_and_inject(app, injector, note=SAMPLE_NOTE)

        # Wait on the last-pasted box, then assert every section landed in its own
        # box -- regardless of the on-screen layout. Compare the whole mapping so a
        # failure dumps every box (where a stray/misrouted section actually went),
        # not just the first mismatch.
        _wait_for_fill(app, "plan", SAMPLE_NOTE["plan"])
        actual = {section: app.box_text(section) for section in SAMPLE_NOTE}
        assert actual == dict(SAMPLE_NOTE), f"layout {layout}: {actual!r}"
