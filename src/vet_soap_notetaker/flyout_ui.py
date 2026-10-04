import tkinter as tk

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.window_icon import apply_window_icon

DEFAULT_WIDTH = 360
DEFAULT_HEIGHT = 320
DEFAULT_MARGIN = 20


class FlyoutWindow(tk.Toplevel):
    def __init__(
        self,
        master,
        soap_text,
        on_copy_and_inject,
        on_copy_to_clipboard,
        on_open_history=None,
    ):
        super().__init__(master)
        apply_window_icon(self)
        self.attributes("-topmost", True)
        self.geometry(
            self.bottom_right_geometry(
                screen_width=self.winfo_screenwidth(),
                screen_height=self.winfo_screenheight(),
                width=DEFAULT_WIDTH,
                height=DEFAULT_HEIGHT,
                margin=DEFAULT_MARGIN,
            )
        )

        # Pack the controls at the bottom *first* so they always reserve their
        # space; the note text then fills whatever's left. Otherwise the
        # full-height Text widget pushes the buttons past the window's bottom
        # edge and they're never seen (which hid "Open History" entirely).
        controls = tk.Frame(self)
        controls.pack(side="bottom", fill="x")

        button_row = tk.Frame(controls)
        button_row.pack(side="bottom")
        self.copy_and_inject_button = tk.Button(
            button_row,
            text=ui_strings.BUTTON_COPY_AND_INJECT,
            command=on_copy_and_inject,
        )
        self.copy_and_inject_button.pack(side="left")

        self.copy_to_clipboard_button = tk.Button(
            button_row,
            text=ui_strings.BUTTON_COPY_SOAP_NOTE,
            command=on_copy_to_clipboard,
        )
        self.copy_to_clipboard_button.pack(side="left")

        # Only offered when there's a note to browse -- error-message flyouts
        # pass no callback and omit the button entirely. Sits on the same row as
        # the copy/inject buttons.
        self.open_history_button = None
        if on_open_history is not None:
            self.open_history_button = tk.Button(
                button_row,
                text=ui_strings.BUTTON_OPEN_HISTORY,
                command=on_open_history,
            )
            self.open_history_button.pack(side="left")

        self.text_widget = tk.Text(self)
        self.text_widget.insert("1.0", soap_text)
        self.text_widget.pack(side="top", fill="both", expand=True)

        self.update()

        # The pre-computed geometry above is only a first guess: the real window
        # manager decorates and may resize the window, so its actual rendered
        # size can push the bottom edge (the buttons) past the usable screen.
        # Re-anchor against the *work area* (screen minus taskbar) using the
        # window's *measured* size, and do it again on the event loop once the WM
        # has finished mapping it, so the bottom is always visible without the
        # user having to drag it up.
        self._anchor_bottom_right()
        self.after(0, self._anchor_bottom_right)

    def _anchor_bottom_right(self):
        self.update_idletasks()
        left, top, right, bottom = self.screen_work_area()
        x, y = self.fit_bottom_right(
            work_left=left,
            work_top=top,
            work_right=right,
            work_bottom=bottom,
            width=self.winfo_width(),
            height=self.winfo_height(),
            margin=DEFAULT_MARGIN,
        )
        self.geometry(f"+{x}+{y}")

    def screen_work_area(self):
        """Usable screen rect ``(left, top, right, bottom)`` in Tk coordinates.

        Momentarily maximizes an invisible probe window: the window manager
        sizes a maximized window to the work area (excluding the taskbar,
        whichever edge it's on), and reading it back stays in Tk's own
        coordinate space -- so it's correct even under Windows DPI scaling, where
        physical ``SPI_GETWORKAREA`` pixels wouldn't line up with Tk's geometry.
        Falls back to the full screen where maximize isn't supported (e.g. the
        X11/headless test environment), leaving behaviour there unchanged.
        """
        probe = None
        try:
            probe = tk.Toplevel(self)
            probe.attributes("-alpha", 0.0)
            probe.state("zoomed")
            probe.update_idletasks()
            left = probe.winfo_rootx()
            top = probe.winfo_rooty()
            right = left + probe.winfo_width()
            bottom = top + probe.winfo_height()
            if right > left and bottom > top:
                return left, top, right, bottom
        except tk.TclError:
            pass
        finally:
            if probe is not None:
                probe.destroy()
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    @staticmethod
    def fit_bottom_right(
        work_left, work_top, work_right, work_bottom, width, height, margin
    ):
        """Bottom-right position that keeps the *whole* window in the work area.

        Anchors to the bottom-right corner of the usable area but never lets the
        left/top edge cross ``margin`` past the work-area edge, so a window
        taller or wider than the screen still shows its bottom-right (where the
        buttons live) rather than running off-edge.
        """
        x = max(work_left + margin, work_right - width - margin)
        y = max(work_top + margin, work_bottom - height - margin)
        return x, y

    @staticmethod
    def bottom_right_geometry(screen_width, screen_height, width, height, margin):
        x, y = FlyoutWindow.fit_bottom_right(
            work_left=0,
            work_top=0,
            work_right=screen_width,
            work_bottom=screen_height,
            width=width,
            height=height,
            margin=margin,
        )
        return f"{width}x{height}+{x}+{y}"
