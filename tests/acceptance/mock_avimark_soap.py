"""Windows-only native-Win32 mock AVImark SOAP screens, for trying calibration.

Unlike the Tkinter ``mock_avimark.py``, these windows are built from **real native
Win32 controls** -- ``EDIT`` boxes and ``BUTTON`` checkboxes, each a genuine child
HWND with its own control id and window class. That matters: VetScribe's
calibration identifies each SOAP box by ``WindowFromPoint`` -> ``GetDlgCtrlID`` /
``GetClassName`` and later re-finds it via ``EnumChildWindows``. Tkinter widgets
aren't native HWNDs (they're drawn by Tk on one toplevel), so they can't exercise
that path at all -- these can.

Five layouts, each arranging the four SOAP boxes differently with unrelated
checkboxes interspersed, so you can see per-box placement work regardless of layout
(and see why a blind "Tab to the next box" count would land in the wrong field):

  1. single column, a checkbox between each box
  2. two columns (S/O top, A/P bottom)
  3. scrambled visual order (Plan at the top, Subjective at the bottom)
  4. a big block of checkboxes wedged between Subjective and Objective
  5. same as 1 but the boxes have NO control id (id 0) -- forces calibration's
     position fallback, the way owner-drawn / unlabeled controls would

Each window's title contains "AVImark" so VetScribe's title marker matches it.

Just look at one:
    python -m tests.acceptance.mock_avimark_soap --layout 3

Watch calibration + injection fill it automatically (window stays open):
    python -m tests.acceptance.mock_avimark_soap --layout 3 --demo
"""

import sys
import time

if sys.platform != "win32":  # pragma: no cover - the whole module is Win32-only
    raise SystemExit("mock_avimark_soap is Windows-only (needs native Win32 controls)")

import win32api
import win32con
import win32gui

from vetscribe.avimark_calibration import SOAP_SECTIONS, CalibrationSession

TITLE_TEMPLATE = "AVImark - [SOAP Demo Layout {n}]"

# Control ids for the four boxes (a stable per-section key, like a real dialog).
# Layout 5 overrides these to 0 to force the position fallback.
_BOX_IDS = {"subjective": 1001, "objective": 1002, "assessment": 1003, "plan": 1004}

_EDIT_STYLE = (
    win32con.WS_CHILD
    | win32con.WS_VISIBLE
    | win32con.WS_BORDER
    | win32con.ES_MULTILINE
    | win32con.ES_AUTOVSCROLL
    | win32con.ES_LEFT
)
_CHECK_STYLE = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_AUTOCHECKBOX
_LABEL_STYLE = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT

_CLASS_NAME = "VetScribeMockAvimarkSoap"
_class_registered = False


def _box(section, x, y, w, h):
    return {"kind": "edit", "section": section, "rect": (x, y, w, h)}


def _check(text, cid, x, y, w=220, h=22):
    return {"kind": "check", "text": text, "id": cid, "rect": (x, y, w, h)}


def _label(text, x, y, w=140, h=18):
    return {"kind": "label", "text": text, "rect": (x, y, w, h)}


def _layout(n):
    """Return (title, client_width, client_height, [items]) for a layout."""
    if n == 1:
        items = [
            _label("Subjective", 20, 10), _box("subjective", 20, 30, 640, 80),
            _check("Eyes normal", 2001, 20, 116),
            _label("Objective", 20, 142), _box("objective", 20, 162, 640, 80),
            _check("Ears normal", 2002, 20, 248),
            _label("Assessment", 20, 274), _box("assessment", 20, 294, 640, 80),
            _check("Recheck in 2 weeks", 2003, 20, 380),
            _label("Plan", 20, 406), _box("plan", 20, 426, 640, 80),
        ]
        return TITLE_TEMPLATE.format(n=n), 700, 525, items
    if n == 2:
        items = [
            _label("Subjective", 20, 10), _box("subjective", 20, 30, 320, 150),
            _label("Objective", 360, 10), _box("objective", 360, 30, 320, 150),
            _check("Eyes normal", 2001, 20, 190),
            _check("Ears normal", 2002, 220, 190),
            _label("Assessment", 20, 220), _box("assessment", 20, 240, 320, 150),
            _label("Plan", 360, 220), _box("plan", 360, 240, 320, 150),
        ]
        return TITLE_TEMPLATE.format(n=n), 720, 410, items
    if n == 3:
        # Scrambled visual order: Plan at top, Subjective at the bottom.
        items = [
            _label("Plan", 20, 10), _box("plan", 20, 30, 640, 80),
            _check("Surgery discussed", 2001, 20, 116),
            _label("Assessment", 20, 142), _box("assessment", 20, 162, 640, 80),
            _check("Bloodwork ordered", 2002, 20, 248),
            _label("Objective", 20, 274), _box("objective", 20, 294, 640, 80),
            _check("Weight recorded", 2003, 20, 380),
            _label("Subjective", 20, 406), _box("subjective", 20, 426, 640, 80),
        ]
        return TITLE_TEMPLATE.format(n=n), 700, 525, items
    if n == 4:
        # A block of checkboxes between Subjective and Objective -- a blind Tab count
        # would march straight through these into the wrong field. Kept compact so
        # the window still fits on the (headless) CI display when cascaded.
        checks = [
            _check(f"Finding #{i + 1}", 2001 + i, 20, 108 + i * 24) for i in range(4)
        ]
        items = [
            _label("Subjective", 20, 10), _box("subjective", 20, 30, 640, 70),
            *checks,
            _label("Objective", 20, 215), _box("objective", 20, 235, 640, 65),
            _label("Assessment", 20, 310), _box("assessment", 20, 330, 640, 65),
            _label("Plan", 20, 405), _box("plan", 20, 425, 640, 65),
        ]
        return TITLE_TEMPLATE.format(n=n), 700, 500, items
    if n == 5:
        title, w, h, items = _layout(1)
        return TITLE_TEMPLATE.format(n=5), w, h, items  # ids zeroed in _create
    raise ValueError(f"unknown layout {n}")


def _ensure_class():
    global _class_registered
    if _class_registered:
        return
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = _CLASS_NAME
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.hbrBackground = win32con.COLOR_BTNFACE + 1
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    wc.lpfnWndProc = {win32con.WM_DESTROY: _on_destroy}
    win32gui.RegisterClass(wc)
    _class_registered = True


def _on_destroy(hwnd, msg, wparam, lparam):
    win32gui.PostQuitMessage(0)
    return 0


class MockAvimarkSoapApp:
    """A native-Win32 AVImark-like SOAP window, created on the current thread."""

    def __init__(self, layout=1):
        self.layout = layout
        self.title, cw, ch, items = _layout(layout)
        self.box_hwnds = {}
        _ensure_class()
        hinst = win32api.GetModuleHandle(None)

        # Pin the window to a fixed on-screen spot near the top-left (so even the
        # tallest layout fits on the headless CI display) and size it so its client
        # area holds the controls. Position matters because calibration locates each
        # box with WindowFromPoint(screen point): the box must be on-screen AND our
        # window must be the top-most one at that point. We make it top-most right
        # after creation (below), which is what actually guarantees WindowFromPoint
        # lands on our control rather than a window underneath (e.g. the CI console)
        # -- cascading (CW_USEDEFAULT) or stacking at the origin both let another
        # window sit over a box and corrupt the capture.
        style = win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE
        self.hwnd = win32gui.CreateWindow(
            _CLASS_NAME, self.title, style,
            20, 10, cw + 40, ch + 60, 0, 0, hinst, None,
        )

        for item in items:
            x, y, w, h = item["rect"]
            if item["kind"] == "label":
                win32gui.CreateWindow(
                    "STATIC", item["text"], _LABEL_STYLE, x, y, w, h,
                    self.hwnd, 0, hinst, None,
                )
            elif item["kind"] == "check":
                win32gui.CreateWindow(
                    "BUTTON", item["text"], _CHECK_STYLE, x, y, w, h,
                    self.hwnd, item["id"], hinst, None,
                )
            elif item["kind"] == "edit":
                section = item["section"]
                cid = 0 if layout == 5 else _BOX_IDS[section]
                child = win32gui.CreateWindow(
                    "EDIT", "", _EDIT_STYLE, x, y, w, h,
                    self.hwnd, cid, hinst, None,
                )
                self.box_hwnds[section] = child

        win32gui.UpdateWindow(self.hwnd)
        # Force this window above everything else (incl. the CI console) so the
        # calibration's WindowFromPoint hits our boxes. SetWindowPos' z-order change
        # is honoured cross-thread, unlike SetForegroundWindow.
        try:
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
        except Exception:
            pass

    def box_rect(self, section):
        return win32gui.GetWindowRect(self.box_hwnds[section])

    def box_center(self, section):
        left, top, right, bottom = self.box_rect(section)
        return (left + right) // 2, (top + bottom) // 2

    def box_text(self, section):
        return win32gui.GetWindowText(self.box_hwnds[section])

    def pump_once(self):
        """Drain any pending messages (so paints/input get processed)."""
        while True:
            status, msg = win32gui.PeekMessage(0, 0, 0, win32con.PM_REMOVE)
            if not status:
                break
            win32gui.TranslateMessage(msg)
            win32gui.DispatchMessage(msg)

    def mainloop(self):
        win32gui.PumpMessages()

    def close(self):
        # DestroyWindow only works on the thread that created the window; this is
        # usually called from another thread, so post WM_CLOSE instead -- PostMessage
        # is thread-safe and queues to the window's own thread, which then runs the
        # default WM_CLOSE -> DestroyWindow -> WM_DESTROY -> PostQuitMessage, ending
        # its PumpMessages(). (Calling DestroyWindow cross-thread silently no-ops and
        # leaks the window, which then looks like a second open AVImark chart.)
        try:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass


SAMPLE_NOTE = {
    "subjective": "Owner reports Max has been vomiting since yesterday, still drinking.",
    "objective": "T 101.8F, HR 110, mucous membranes pink, abdomen soft & non-painful.",
    "assessment": "Likely dietary-indiscretion gastroenteritis; no evidence of obstruction.",
    "plan": "Bland diet 3 days, metoclopramide, recheck if vomiting persists past 48h.",
}


def note_fields(note=None):
    note = note or SAMPLE_NOTE
    return [(section, note[section]) for section in SOAP_SECTIONS]


def calibrate_and_inject(app, injector, note=None, delay=0.0):
    """Calibrate against the mock's boxes and inject the note, per box.

    Feeds the real ``capture_calibration_box`` the centre of each box (what a vet's
    click would land on), then injects with ``focus_and_inject_fields_calibrated``.
    Returns the ``BoxCalibration`` used. Call this from a *different* thread than
    the one running ``app.mainloop()`` (cross-thread focus is the real injection
    path, and same-thread AttachThreadInput is invalid).
    """
    session = CalibrationSession(capture_fn=injector.capture_calibration_box)
    for section in SOAP_SECTIONS:
        cx, cy = app.box_center(section)
        session.record_click(cx, cy)
        if delay:
            time.sleep(delay)
    calibration = session.result()

    # Target this specific mock window (like the real app remembering the active
    # chart). Without it, any *other* open "AVImark"-titled window -- e.g. a plain
    # mock left over from an earlier run -- makes the injector refuse to guess which
    # chart to paste into.
    injector.target_hwnd = app.hwnd

    fields = note_fields(note)
    fallback = "\n\n".join(text for _, text in fields if text)
    injector.focus_and_inject_fields_calibrated(fields, calibration, fallback)
    return calibration


def _run_demo(layout):
    """Show a layout and auto-calibrate+inject against it, leaving it on screen."""
    import threading

    from vetscribe.avimark_injector import AvimarkInjector

    app = MockAvimarkSoapApp(layout=layout)

    def _drive():
        time.sleep(1.0)  # let the window settle and come to the foreground
        injector = AvimarkInjector(title_marker="AVImark")
        calibrate_and_inject(app, injector, delay=0.4)
        print("Injected. Each SOAP section should now be in its own box.")

    threading.Thread(target=_drive, daemon=True).start()
    app.mainloop()


def main():
    args = sys.argv[1:]
    layout = 1
    if "--layout" in args:
        layout = int(args[args.index("--layout") + 1])
    if "--demo" in args:
        _run_demo(layout)
    else:
        MockAvimarkSoapApp(layout=layout).mainloop()


if __name__ == "__main__":
    main()
