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


# --- set a control's text directly (no focus / clipboard / keystroke) ---------


def test_set_control_text_inserts_via_edit_messages(mocker):
    win32gui = mocker.patch("vetscribe.avimark_injector.win32gui")
    from vetscribe import avimark_injector as mod

    injector = AvimarkInjector()
    injector._set_control_text(555, "hello")

    # Select the whole control then replace the selection: SendMessage marshals to
    # the control's own thread, so the text lands in *this exact* hwnd with no focus
    # race, no clipboard contention, and no dependence on the foreground window.
    assert win32gui.SendMessage.call_args_list == [
        mocker.call(555, mod._EM_SETSEL, 0, -1),
        mocker.call(555, mod._EM_REPLACESEL, 1, "hello"),
    ]


# --- _paste_calibrated -------------------------------------------------------


def test_paste_calibrated_sets_each_box_text_in_order(mocker):
    injector = AvimarkInjector()
    hwnds = {"subjective": 1, "objective": 2, "assessment": 3, "plan": 4}
    mocker.patch.object(
        injector, "resolve_calibration_box", side_effect=lambda parent, box: _hwnd_for(box, hwnds)
    )
    setter = mocker.patch.object(injector, "_set_control_text")

    ok = injector._paste_calibrated(999, _fields(), _full_calibration())

    assert ok is True
    # each section's text set straight into its own resolved control, in SOAP order
    assert setter.call_args_list == [
        mocker.call(1, "S text"),
        mocker.call(2, "O text"),
        mocker.call(3, "A text"),
        mocker.call(4, "P text"),
    ]


def test_paste_calibrated_sets_distinct_controls_for_distinct_boxes(mocker):
    # Regression guard for the "S/O/A filled but Plan empty" bug: each box must get
    # its own control. If two boxes resolve to the same hwnd we must abort rather
    # than let one box's text overwrite/append into another's.
    injector = AvimarkInjector()

    def resolve(parent, box):
        # plan collides onto the assessment control
        return 3 if box.control_id in (1002, 1003) else {1000: 1, 1001: 2}[box.control_id]

    mocker.patch.object(injector, "resolve_calibration_box", side_effect=resolve)
    setter = mocker.patch.object(injector, "_set_control_text")

    ok = injector._paste_calibrated(999, _fields(), _full_calibration())

    assert ok is False
    setter.assert_not_called()


def test_paste_calibrated_bails_without_pasting_if_a_box_is_unresolved(mocker):
    injector = AvimarkInjector()

    def resolve(parent, box):
        # fail to resolve the assessment box; the others resolve to distinct hwnds
        return None if box.control_id == 1002 else 40 + box.control_id

    mocker.patch.object(injector, "resolve_calibration_box", side_effect=resolve)
    setter = mocker.patch.object(injector, "_set_control_text")

    ok = injector._paste_calibrated(999, _fields(), _full_calibration())

    assert ok is False
    # nothing set -- we resolve everything first, then paste, so a miss aborts cleanly
    setter.assert_not_called()


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
    mocker.patch.object(injector, "_resolve_target", return_value=None)
    paste = mocker.patch.object(injector, "_paste_calibrated")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "blob")

    assert ok is False
    paste.assert_not_called()


def test_focus_and_inject_fields_calibrated_pastes_per_box_without_requiring_foreground(mocker):
    # The per-box paste uses SendMessage straight to each control, so it must NOT
    # bail just because the window couldn't be brought to the foreground -- that was
    # the "all four boxes empty" layout-4 regression.
    injector = AvimarkInjector()
    mocker.patch.object(injector, "_resolve_target", return_value=42)
    raise_window = mocker.patch.object(injector, "_raise_window")
    mocker.patch.object(injector, "_paste_calibrated", return_value=True)
    mocker.patch.object(injector, "is_avimark_foreground", return_value=False)
    copy = mocker.patch.object(injector, "copy_to_clipboard")
    ctrl_v = mocker.patch.object(injector, "_send_ctrl_v")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "blob")

    assert ok is True
    raise_window.assert_called_once_with(42)  # still raise it so the vet sees it fill
    # no single-blob fallback when per-box succeeded
    copy.assert_not_called()
    ctrl_v.assert_not_called()


def test_focus_and_inject_fields_calibrated_falls_back_to_single_blob_when_foreground(mocker):
    injector = AvimarkInjector()
    mocker.patch.object(injector, "_resolve_target", return_value=42)
    mocker.patch.object(injector, "_raise_window")
    mocker.patch.object(injector, "_paste_calibrated", return_value=False)
    mocker.patch.object(injector, "is_avimark_foreground", return_value=True)
    copy = mocker.patch.object(injector, "copy_to_clipboard")
    ctrl_v = mocker.patch.object(injector, "_send_ctrl_v")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "the blob")

    # still reports success: the note landed, just as one block in the focused box
    assert ok is True
    copy.assert_called_once_with("the blob")
    ctrl_v.assert_called_once()


def test_focus_and_inject_fields_calibrated_fallback_refuses_when_not_foreground(mocker):
    # The single-block fallback uses a global Ctrl+V, which DOES need AVImark
    # foreground; if it isn't, refuse rather than paste into the wrong app (the note
    # is left on the clipboard for a manual paste).
    injector = AvimarkInjector()
    mocker.patch.object(injector, "_resolve_target", return_value=42)
    mocker.patch.object(injector, "_raise_window")
    mocker.patch.object(injector, "_paste_calibrated", return_value=False)
    mocker.patch.object(injector, "is_avimark_foreground", return_value=False)
    ctrl_v = mocker.patch.object(injector, "_send_ctrl_v")
    copy = mocker.patch.object(injector, "copy_to_clipboard")

    ok = injector.focus_and_inject_fields_calibrated(_fields(), _full_calibration(), "the blob")

    assert ok is False
    ctrl_v.assert_not_called()
    # note is left on the clipboard so the vet can paste it manually
    copy.assert_called_once_with("the blob")
