"""Tests for the calibrated (per-box) injection path on AvimarkInjector.

The pure matching is covered in test_avimark_calibration.py; here we pin the Win32
glue -- capturing a control under the cursor, enumerating a window's children,
focusing a specific control cross-thread, and pasting each SOAP section into its
own box -- by patching the win32* modules, the same way the rest of the injector
tests do.
"""

import pytest

from vetscribe.avimark_calibration import SOAP_SECTIONS, BoxCalibration, BoxControl
from vetscribe.avimark_injector import AvimarkInjector


def _full_calibration():
    return BoxCalibration(
        boxes={
            section: BoxControl(control_id=1000 + i, class_name="Edit", rel_x=0.1, rel_y=0.1 * i)
            for i, section in enumerate(SOAP_SECTIONS)
        }
    )


def _fields(**overrides):
    base = {
        "subjective": "S text",
        "objective": "O text",
        "assessment": "A text",
        "plan": "P text",
    }
    base.update(overrides)
    return [(section, base[section]) for section in SOAP_SECTIONS]


# --- capture -----------------------------------------------------------------


def test_capture_calibration_box_builds_descriptor_from_the_click(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    win32gui.WindowFromPoint.return_value = 500
    win32gui.GetDlgCtrlID.return_value = 1007
    win32gui.GetClassName.return_value = "RichEdit20W"
    win32gui.GetAncestor.return_value = 100  # top-level AVImark window
    win32gui.GetWindowRect.return_value = (0, 0, 400, 400)

    injector = AvimarkInjector()
    box = injector.capture_calibration_box(100, 200)

    win32gui.WindowFromPoint.assert_called_once_with((100, 200))
    assert box.control_id == 1007
    assert box.class_name == "RichEdit20W"
    assert box.rel_x == pytest.approx(0.25)  # 100 / 400
    assert box.rel_y == pytest.approx(0.5)  # 200 / 400


# --- resolve -----------------------------------------------------------------


def _fake_enum(win32gui, children):
    """Wire the patched win32gui so EnumChildWindows + getters describe `children`.

    `children` maps hwnd -> (control_id, class_name, rect).
    """

    def enum(parent, callback, extra):
        for hwnd in children:
            callback(hwnd, extra)

    win32gui.EnumChildWindows.side_effect = enum
    win32gui.GetDlgCtrlID.side_effect = lambda h: children[h][0]
    win32gui.GetClassName.side_effect = lambda h: children[h][1]

    rects = {h: children[h][2] for h in children}
    rects[999] = (0, 0, 1000, 1000)  # the parent window's rect

    win32gui.GetWindowRect.side_effect = lambda h: rects[h]


def test_resolve_calibration_box_matches_the_enumerated_child_by_id(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    _fake_enum(
        win32gui,
        {
            10: (1000, "Edit", (0, 0, 100, 100)),
            20: (1002, "Edit", (0, 200, 100, 300)),  # the one we want
            30: (1003, "Edit", (0, 400, 100, 500)),
        },
    )
    box = BoxControl(control_id=1002, class_name="Edit", rel_x=0.0, rel_y=0.0)

    injector = AvimarkInjector()
    assert injector.resolve_calibration_box(999, box) == 20


def test_resolve_calibration_box_returns_none_when_no_children(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    _fake_enum(win32gui, {})
    box = BoxControl(control_id=1002, class_name="Edit", rel_x=0.0, rel_y=0.0)

    injector = AvimarkInjector()
    assert injector.resolve_calibration_box(999, box) is None


# --- focus a control cross-thread --------------------------------------------


def test_focus_control_attaches_thread_input_then_sets_focus(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    win32process = mocker.patch("vetscribe.avimark_injector.win32process")
    win32api = mocker.patch("vetscribe.avimark_injector.win32api")
    win32process.GetWindowThreadProcessId.return_value = (4242, 777)
    win32api.GetCurrentThreadId.return_value = 11

    injector = AvimarkInjector()
    injector._focus_control(555)

    # attach, focus, detach -- in that order
    assert win32process.AttachThreadInput.call_args_list == [
        mocker.call(11, 4242, True),
        mocker.call(11, 4242, False),
    ]
    win32gui.SetFocus.assert_called_once_with(555)


def test_focus_control_detaches_even_if_set_focus_raises(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    win32process = mocker.patch("vetscribe.avimark_injector.win32process")
    win32api = mocker.patch("vetscribe.avimark_injector.win32api")
    win32process.GetWindowThreadProcessId.return_value = (4242, 777)
    win32api.GetCurrentThreadId.return_value = 11
    win32gui.SetFocus.side_effect = RuntimeError("boom")

    injector = AvimarkInjector()
    with pytest.raises(RuntimeError):
        injector._focus_control(555)

    # the detach still ran so we never leave threads attached
    assert win32process.AttachThreadInput.call_args_list[-1] == mocker.call(11, 4242, False)


# --- _paste_calibrated -------------------------------------------------------


def test_paste_calibrated_focuses_and_pastes_each_box_in_order(mocker):
    injector = AvimarkInjector()
    hwnds = {"subjective": 1, "objective": 2, "assessment": 3, "plan": 4}
    mocker.patch.object(
        injector, "resolve_calibration_box", side_effect=lambda parent, box: _hwnd_for(box, hwnds)
    )
    focus = mocker.patch.object(injector, "_focus_control")
    copy = mocker.patch.object(injector, "copy_to_clipboard")
    paste = mocker.patch.object(injector, "_send_ctrl_v")
    mocker.patch("vetscribe.avimark_injector.time.sleep")

    ok = injector._paste_calibrated(999, _fields(), _full_calibration())

    assert ok is True
    # each box focused before its text is pasted, in SOAP order
    assert [c.args[0] for c in focus.call_args_list] == [1, 2, 3, 4]
    assert [c.args[0] for c in copy.call_args_list] == ["S text", "O text", "A text", "P text"]
    assert paste.call_count == 4


def test_paste_calibrated_bails_without_pasting_if_a_box_is_unresolved(mocker):
    injector = AvimarkInjector()

    def resolve(parent, box):
        # fail to resolve the assessment box
        return None if box.control_id == 1002 else 42

    mocker.patch.object(injector, "resolve_calibration_box", side_effect=resolve)
    focus = mocker.patch.object(injector, "_focus_control")
    copy = mocker.patch.object(injector, "copy_to_clipboard")
    paste = mocker.patch.object(injector, "_send_ctrl_v")

    ok = injector._paste_calibrated(999, _fields(), _full_calibration())

    assert ok is False
    # nothing pasted -- we resolve everything first, then paste, so a miss aborts cleanly
    focus.assert_not_called()
    copy.assert_not_called()
    paste.assert_not_called()


def _hwnd_for(box, hwnds):
    # map the calibration BoxControl back to its section via control_id
    for i, section in enumerate(SOAP_SECTIONS):
        if box.control_id == 1000 + i:
            return hwnds[section]
    return None


# --- inject_fields_calibrated ------------------------------------------------


def test_inject_fields_calibrated_refuses_when_avimark_not_foreground(mocker):
    injector = AvimarkInjector()
    mocker.patch.object(injector, "is_avimark_foreground", return_value=False)
    paste = mocker.patch.object(injector, "_paste_calibrated")

    assert injector.inject_fields_calibrated(_fields(), _full_calibration()) is False
    paste.assert_not_called()


def test_inject_fields_calibrated_pastes_into_the_foreground_window(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    win32gui.GetForegroundWindow.return_value = 321
    injector = AvimarkInjector()
    mocker.patch.object(injector, "is_avimark_foreground", return_value=True)
    paste = mocker.patch.object(injector, "_paste_calibrated", return_value=True)

    assert injector.inject_fields_calibrated(_fields(), _full_calibration()) is True
    paste.assert_called_once()
    assert paste.call_args.args[0] == 321  # parent = foreground window


# --- focus_and_inject_fields_calibrated --------------------------------------


def test_focus_and_inject_fields_calibrated_refuses_when_no_target(mocker):
    injector = AvimarkInjector()
    mocker.patch.object(injector, "_resolve_and_focus_target", return_value=None)
    paste = mocker.patch.object(injector, "_paste_calibrated")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "blob")

    assert ok is False
    paste.assert_not_called()


def test_focus_and_inject_fields_calibrated_pastes_per_box_when_resolved(mocker):
    injector = AvimarkInjector()
    mocker.patch.object(injector, "_resolve_and_focus_target", return_value=42)
    mocker.patch.object(injector, "_paste_calibrated", return_value=True)
    copy = mocker.patch.object(injector, "copy_to_clipboard")
    paste = mocker.patch.object(injector, "_send_ctrl_v")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "blob")

    assert ok is True
    # no single-blob fallback when per-box succeeded
    copy.assert_not_called()
    paste.assert_not_called()


def test_focus_and_inject_fields_calibrated_falls_back_to_single_blob(mocker):
    injector = AvimarkInjector()
    mocker.patch.object(injector, "_resolve_and_focus_target", return_value=42)
    mocker.patch.object(injector, "_paste_calibrated", return_value=False)
    copy = mocker.patch.object(injector, "copy_to_clipboard")
    paste = mocker.patch.object(injector, "_send_ctrl_v")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "the blob")

    # still reports success: the note landed, just as one block in the focused box
    assert ok is True
    copy.assert_called_once_with("the blob")
    paste.assert_called_once()
