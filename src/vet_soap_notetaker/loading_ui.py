"""The "Vet Soap Notetaker / Opening History…" splash.

Shown while History loads: from the launcher before the app's heavy imports on a
cold launch, and from ``build_app``'s ``open_history`` while the backend history
is fetched. Keep the imports light -- the launcher imports this module before
anything else so the splash can appear within a fraction of a second.
"""

import tkinter as tk

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.window_icon import apply_window_icon

WIDTH = 320
HEIGHT = 110


class LoadingWindow(tk.Toplevel):
    """A regular window, so it has the usual title bar X. Closing it with the X
    cancels the open (``cancelled``, then ``on_cancel()``); what that means --
    skip History, or quit the app a launch just started -- is the owner's call.
    It opens in front but isn't topmost: the vet can bring other windows over it.
    """

    def __init__(self, master):
        super().__init__(master)
        self.withdraw()
        self.title(ui_strings.SPLASH_TITLE)
        apply_window_icon(self)
        self.resizable(False, False)
        self.cancelled = False
        self.on_cancel = None
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        tk.Label(self, text=ui_strings.SPLASH_TITLE, font=("Segoe UI", 16, "bold")).pack(
            pady=(24, 4)
        )
        tk.Label(self, text=ui_strings.SPLASH_LOADING_MESSAGE).pack()
        x = (self.winfo_screenwidth() - WIDTH) // 2
        y = (self.winfo_screenheight() - HEIGHT) // 2
        self.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    def show(self):
        self.deiconify()
        self.lift()
        # Paint now: the caller goes straight into blocking work (imports, the
        # history fetch) that keeps the Tk loop from drawing it otherwise.
        self.update()

    def _cancel(self):
        if self.cancelled:
            return
        self.cancelled = True
        self.close()
        if self.on_cancel is not None:
            self.on_cancel()

    def close(self):
        try:
            if self.winfo_exists():
                self.destroy()
        except tk.TclError:
            pass
