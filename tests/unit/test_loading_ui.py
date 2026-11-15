import tkinter

import pytest

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.loading_ui import LoadingWindow


@pytest.fixture
def tk_root():
    root = tkinter.Tk()
    root.withdraw()
    yield root
    root.destroy()


def _label_texts(window):
    return [child.cget("text") for child in window.winfo_children() if isinstance(child, tkinter.Label)]


def test_splash_names_the_app_and_says_history_is_opening(tk_root):
    splash = LoadingWindow(tk_root)

    texts = _label_texts(splash)

    assert ui_strings.SPLASH_TITLE == "Vet Soap Notetaker"
    assert ui_strings.SPLASH_TITLE in texts
    assert ui_strings.SPLASH_LOADING_MESSAGE in texts


def test_splash_has_a_title_bar_with_a_close_button(tk_root):
    splash = LoadingWindow(tk_root)
    splash.show()

    # A regular window frame, so the vet gets the usual X to back out.
    assert not splash.overrideredirect()
    assert splash.protocol("WM_DELETE_WINDOW")


def test_closing_the_splash_with_its_x_cancels_it(tk_root):
    splash = LoadingWindow(tk_root)
    cancels = []
    splash.on_cancel = lambda: cancels.append(True)
    splash.show()

    splash.tk.call(splash.protocol("WM_DELETE_WINDOW"))

    assert splash.cancelled
    assert cancels == [True]
    assert not _exists(splash)


def test_closing_the_splash_programmatically_is_not_a_cancel(tk_root):
    splash = LoadingWindow(tk_root)
    splash.show()

    splash.close()

    assert not splash.cancelled


def test_splash_is_not_topmost_so_other_windows_can_cover_it(tk_root):
    splash = LoadingWindow(tk_root)
    splash.show()

    # It opens in front, but the vet can still bring AVImark (or anything else)
    # over it while History loads.
    assert not splash.attributes("-topmost")


def test_show_maps_the_splash_straight_away(tk_root):
    splash = LoadingWindow(tk_root)

    splash.show()

    # Painted before the caller's blocking work, not on the next loop turn.
    assert splash.winfo_ismapped()


def test_close_removes_the_splash_and_is_safe_to_repeat(tk_root):
    splash = LoadingWindow(tk_root)
    splash.show()

    splash.close()
    splash.close()

    assert not _exists(splash)


def _exists(window):
    try:
        return bool(window.winfo_exists())
    except tkinter.TclError:
        return False
