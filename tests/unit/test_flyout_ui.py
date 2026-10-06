import tkinter

import pytest

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.flyout_ui import FlyoutWindow


@pytest.fixture
def tk_root():
    root = tkinter.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_flyout_window_displays_soap_note_text(tk_root):
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="SUBJECTIVE: text\nOBJECTIVE: text\nASSESSMENT: text\nPLAN: text",
        on_copy_and_inject=lambda: None,
        on_copy_to_clipboard=lambda: None,
    )

    displayed_text = flyout.text_widget.get("1.0", "end-1c")

    assert "SUBJECTIVE: text" in displayed_text
    assert "PLAN: text" in displayed_text


def test_flyout_window_has_branded_title(tk_root):
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="text",
        on_copy_and_inject=lambda: None,
        on_copy_to_clipboard=lambda: None,
    )

    # Without an explicit title the window shows Tk's default "tk" in the
    # taskbar; brand it so the vet sees what the pop-out belongs to.
    assert flyout.title() == ui_strings.FLYOUT_WINDOW_TITLE


def test_copy_and_inject_button_has_expected_label_and_sends_current_text(tk_root):
    calls = []
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="text",
        on_copy_and_inject=calls.append,
        on_copy_to_clipboard=lambda text: None,
    )

    assert flyout.copy_and_inject_button["text"] == ui_strings.BUTTON_COPY_AND_INJECT
    flyout.copy_and_inject_button.invoke()
    # The callback receives the note currently shown, not a value captured when
    # the flyout opened -- so a last-second edit here isn't lost on inject.
    assert calls == ["text"]


def test_copy_to_clipboard_button_has_expected_label_and_sends_current_text(tk_root):
    calls = []
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="text",
        on_copy_and_inject=lambda text: None,
        on_copy_to_clipboard=calls.append,
    )

    assert flyout.copy_to_clipboard_button["text"] == ui_strings.BUTTON_COPY_SOAP_NOTE
    flyout.copy_to_clipboard_button.invoke()
    assert calls == ["text"]


def test_inject_and_copy_send_the_vets_edited_text(tk_root):
    injected = []
    copied = []
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="original note",
        on_copy_and_inject=injected.append,
        on_copy_to_clipboard=copied.append,
    )

    # The vet tweaks the note in the pop-out before acting on it.
    flyout.text_widget.delete("1.0", "end")
    flyout.text_widget.insert("1.0", "edited note")

    flyout.copy_and_inject_button.invoke()
    flyout.copy_to_clipboard_button.invoke()

    assert injected == ["edited note"]
    assert copied == ["edited note"]


def test_open_history_button_invokes_callback_when_provided(tk_root):
    calls = []
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="text",
        on_copy_and_inject=lambda: None,
        on_copy_to_clipboard=lambda: None,
        on_open_history=lambda: calls.append("history"),
    )

    assert flyout.open_history_button["text"] == ui_strings.BUTTON_OPEN_HISTORY
    flyout.open_history_button.invoke()
    assert calls == ["history"]


def test_button_row_is_pinned_to_the_bottom_so_a_tall_note_cant_hide_it(
    tk_root,
):
    # Regression: the note Text used to be packed first with no size limit, so a
    # long note pushed the buttons below the window's bottom edge and out of
    # sight. The controls must stay pinned to the bottom while the note fills the
    # space above them. Open History shares the button row, packed alongside the
    # copy/inject buttons.
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="line\n" * 200,
        on_copy_and_inject=lambda: None,
        on_copy_to_clipboard=lambda: None,
        on_open_history=lambda: None,
    )

    text_info = flyout.text_widget.pack_info()
    assert text_info["side"] == "top"
    assert str(text_info["expand"]) in ("1", "True")
    assert text_info["fill"] == "both"
    button_row = flyout.open_history_button.master
    assert button_row.pack_info()["side"] == "bottom"
    assert flyout.open_history_button.pack_info()["side"] == "left"


def test_open_history_button_is_absent_when_no_callback_is_given(tk_root):
    # Error-message flyouts have no note to browse, so they omit the button.
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="text",
        on_copy_and_inject=lambda: None,
        on_copy_to_clipboard=lambda: None,
    )

    assert flyout.open_history_button is None


def test_flyout_window_is_topmost(tk_root):
    flyout = FlyoutWindow(
        master=tk_root,
        soap_text="text",
        on_copy_and_inject=lambda: None,
        on_copy_to_clipboard=lambda: None,
    )

    assert flyout.attributes("-topmost") == 1


def test_bottom_right_geometry_places_window_in_bottom_right_corner_with_margin():
    geometry = FlyoutWindow.bottom_right_geometry(
        screen_width=1920, screen_height=1080, width=400, height=300, margin=20
    )

    assert geometry == "400x300+1500+760"


def test_fit_bottom_right_anchors_to_the_bottom_right_corner():
    x, y = FlyoutWindow.fit_bottom_right(
        work_left=0,
        work_top=0,
        work_right=1920,
        work_bottom=1080,
        width=400,
        height=300,
        margin=20,
    )

    assert (x, y) == (1500, 760)


def test_fit_bottom_right_keeps_the_bottom_above_the_taskbar():
    # The taskbar shrinks the usable area: work_bottom is 1032, not 1080. The
    # window bottom (y + height) must land at work_bottom - margin so the buttons
    # sit above the taskbar instead of being hidden behind it.
    work_bottom = 1080 - 48
    _, y = FlyoutWindow.fit_bottom_right(
        work_left=0,
        work_top=0,
        work_right=1920,
        work_bottom=work_bottom,
        width=400,
        height=300,
        margin=20,
    )

    assert y + 300 == work_bottom - 20


def test_fit_bottom_right_keeps_bottom_visible_when_window_is_taller_than_screen():
    # If the real rendered window is taller than the usable height, anchoring to
    # the bottom would push the top (and thus the whole thing) off-screen. The
    # top is clamped to the margin so the bottom edge -- the buttons -- stays on
    # screen instead of being cut off.
    _, y = FlyoutWindow.fit_bottom_right(
        work_left=0,
        work_top=0,
        work_right=1920,
        work_bottom=1080,
        width=400,
        height=2000,
        margin=20,
    )

    assert y == 20
