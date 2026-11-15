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


def test_splash_is_borderless(tk_root):
    splash = LoadingWindow(tk_root)
    splash.show()

    # No title bar, so the vet can't close it half-way.
    assert splash.overrideredirect()


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
