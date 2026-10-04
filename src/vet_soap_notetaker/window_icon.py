"""Give Tk windows the Vet Soap Notetaker dog logo instead of Tk's default feather.

Setting the icon on the root with ``default=True`` is supposed to cascade to
every Toplevel, but in practice new Toplevels (the flyout / settings / history
windows) can still come up with Tk's stock icon, so each window applies it
itself via ``apply_window_icon``.
"""

import logging
import sys
import tkinter as tk

from vet_soap_notetaker.paths import get_asset_path

logger = logging.getLogger("vet_soap_notetaker.window_icon")


def apply_window_icon(window) -> None:
    # Best-effort: a missing or undecodable asset must never stop a window (or
    # the whole app) from opening.
    try:
        if sys.platform == "win32":
            # The .ico carries every size Windows wants for the title bar and
            # taskbar; default=True also makes it the app-wide default.
            window.iconbitmap(default=str(get_asset_path("vet_soap_notetaker.ico")))
        else:
            # Elsewhere Tk only understands a PhotoImage. Keep a reference on the
            # window so it isn't garbage-collected out from under Tk.
            icon = tk.PhotoImage(master=window, file=str(get_asset_path("vet_soap_notetaker.png")))
            window._vet_soap_notetaker_icon = icon
            window.iconphoto(True, icon)
    except Exception:
        logger.warning("Could not set window icon", exc_info=True)
