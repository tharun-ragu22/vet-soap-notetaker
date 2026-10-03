import logging

import win32api
import win32clipboard
import win32con
import win32gui

from vetscribe.avimark_calibration import choose_control, descriptor_from_capture

AVIMARK_TITLE_MARKER = "AVImark"

# win32con may not carry GA_ROOT on every build; it's a fixed Win32 constant.
_GA_ROOT = getattr(win32con, "GA_ROOT", 2)

# Edit-control messages used to drop a section's text straight into one box
# (fixed Win32 constants; fall back to their literal values if win32con lacks them).
_EM_SETSEL = getattr(win32con, "EM_SETSEL", 0x00B1)
_EM_REPLACESEL = getattr(win32con, "EM_REPLACESEL", 0x00C2)

logger = logging.getLogger("vetscribe.avimark_injector")


class AvimarkInjector:
    def __init__(self, title_marker: str = AVIMARK_TITLE_MARKER):
        self.title_marker = title_marker
        # The specific AVImark window the vet was working in when the flyout
        # appeared. focus_and_inject pastes into this exact window so that,
        # with several patient charts open, the note lands in the right one.
        self.target_hwnd = None

    def is_avimark_foreground(self) -> bool:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        logger.debug("foreground window title: %r", title)
        return self.title_marker.lower() in title.lower()

    def copy_to_clipboard(self, text: str):
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

    def inject(self, text: str) -> bool:
        if not self.is_avimark_foreground():
            logger.warning("injection skipped: AVImark is not the foreground window")
            return False
        self.copy_to_clipboard(text)
        self._send_ctrl_v()
        logger.info("SOAP note injected into AVImark")
        return True

    def find_avimark_windows(self):
        """Return the hwnds of every visible top-level AVImark window.

        Matches the same configured title marker as ``is_avimark_foreground``.
        Ordered as ``EnumWindows`` yields them, i.e. top-most in the Z-order
        first.
        """
        matches = []

        def _collect(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if self.title_marker.lower() in title.lower():
                    results.append(hwnd)
            # Return True so enumeration continues to every top-level window;
            # pywin32 stops the walk the moment the callback returns falsy.
            return True

        win32gui.EnumWindows(_collect, matches)
        return matches

    def find_avimark_window(self):
        """Return one visible top-level AVImark window (top-most), or None."""
        matches = self.find_avimark_windows()
        return matches[0] if matches else None

    def remember_active_window(self):
        """Record the currently-foreground AVImark window as the paste target.

        Called just before a flyout / history window is shown, while the vet's
        AVImark chart is still in front, to seed the target for the common case
        where they inject without navigating away. ``track_active_window`` then
        keeps it current. If the foreground isn't an AVImark window (e.g.
        History was opened from the tray menu), the target is cleared and
        injection falls back to auto-detection. Best-effort: a failing Win32
        call must never break showing the flyout.
        """
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            self.target_hwnd = None
            return
        if self.title_marker.lower() in title.lower():
            self.target_hwnd = hwnd
            logger.debug("remembered active AVImark window %s (%r)", hwnd, title)
        else:
            self.target_hwnd = None

    def track_active_window(self):
        """Follow the vet to whichever AVImark chart they switch to.

        Polled on a timer while a flyout / history window is open. If an AVImark
        window is currently in front, it becomes the paste target; otherwise
        (our own flyout is in front, another app, etc.) the last AVImark target
        is left untouched -- so Copy & Inject lands in the chart the vet was
        *most recently* in, following their latest navigation. Best-effort.
        """
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return
        if self.title_marker.lower() in title.lower():
            self.target_hwnd = hwnd

    def _remembered_target(self):
        """The remembered AVImark window if it's still open and still AVImark."""
        hwnd = self.target_hwnd
        if hwnd is None:
            return None
        try:
            if not win32gui.IsWindow(hwnd):
                return None
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return None
        if self.title_marker.lower() not in title.lower():
            return None
        return hwnd

    def _resolve_and_focus_target(self, fallback_text: str):
        """Locate the AVImark paste target, raise it, and confirm it's foreground.

        Shared by the single-blob and per-field "Copy & Inject" paths. Returns
        the target hwnd once AVImark is genuinely the foreground window, or None
        if we can't safely paste. We prefer the exact window recorded by
        ``remember_active_window`` (the chart the vet was in); if that's gone and
        several AVImark windows are open we can't tell which patient is meant, so
        we refuse and leave ``fallback_text`` on the clipboard for a manual
        Ctrl+V rather than risk the wrong chart.
        """
        hwnd = self._remembered_target()
        if hwnd is None:
            matches = self.find_avimark_windows()
            if not matches:
                logger.warning("injection skipped: no AVImark window found")
                return None
            if len(matches) > 1:
                logger.warning(
                    "injection skipped: %d AVImark windows open and none was "
                    "recorded as the active chart; note copied to clipboard for "
                    "manual paste",
                    len(matches),
                )
                self.copy_to_clipboard(fallback_text)
                return None
            hwnd = matches[0]
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        if not self.is_avimark_foreground():
            logger.warning(
                "injection skipped: could not bring AVImark to the foreground"
            )
            return None
        return hwnd

    def focus_and_inject(self, text: str) -> bool:
        """Bring AVImark to the foreground ourselves, then paste into it.

        This is the path for the flyout / history "Copy & Inject" buttons: the
        vet clicks our window, so AVImark is *not* the foreground window and the
        plain ``inject`` guard would (correctly) refuse. Here we actively locate
        the AVImark window, raise it, and only paste once we've confirmed it's
        genuinely the foreground window -- so the note still can't land in the
        wrong application. Whatever field the caret was last in inside AVImark is
        where the paste goes; we can't target a specific field.
        """
        hwnd = self._resolve_and_focus_target(text)
        if hwnd is None:
            return False
        self.copy_to_clipboard(text)
        self._send_ctrl_v()
        logger.info("SOAP note injected into AVImark")
        return True

    # --- calibrated per-box injection ---------------------------------------
    #
    # We can't fill the four SOAP boxes by Tabbing between them -- unrelated
    # checkboxes sit in the keyboard order, so a blind Tab count lands in the wrong
    # field. Instead each box is targeted by its actual Win32 control, captured
    # once by `capture_calibration_box` and resolved back with `resolve_calibration_box`.
    # See avimark_calibration.py for the (pure) descriptor model and matching.

    def capture_calibration_box(self, screen_x: int, screen_y: int):
        """Identify the control under a calibration click as a ``BoxControl``.

        Called while the vet clicks inside one of AVImark's boxes during setup.
        Records the control's id/class and the click position relative to the
        top-level AVImark window, so it can be re-found later even after the window
        is recreated for a different patient.
        """
        hwnd = win32gui.WindowFromPoint((screen_x, screen_y))
        control_id = win32gui.GetDlgCtrlID(hwnd)
        class_name = win32gui.GetClassName(hwnd)
        top = win32gui.GetAncestor(hwnd, _GA_ROOT)
        parent_rect = win32gui.GetWindowRect(top)
        return descriptor_from_capture(
            control_id, class_name, parent_rect, screen_x, screen_y
        )

    def _enumerate_candidates(self, parent_hwnd):
        """List every child control of ``parent_hwnd`` with its id/class/rect."""
        results = []

        def _collect(hwnd, _extra):
            results.append(
                {
                    "hwnd": hwnd,
                    "control_id": win32gui.GetDlgCtrlID(hwnd),
                    "class_name": win32gui.GetClassName(hwnd),
                    "rect": win32gui.GetWindowRect(hwnd),
                }
            )
            return True

        win32gui.EnumChildWindows(parent_hwnd, _collect, None)
        return results

    def resolve_calibration_box(self, parent_hwnd, box):
        """Resolve a calibrated ``box`` back to a live control hwnd under the window."""
        candidates = self._enumerate_candidates(parent_hwnd)
        parent_rect = win32gui.GetWindowRect(parent_hwnd)
        return choose_control(candidates, box, parent_rect)

    def _set_control_text(self, hwnd, text):
        """Insert ``text`` straight into one EDIT/RichEdit control.

        Selects the control's whole contents and replaces the selection, both via
        ``SendMessage`` -- which marshals to the control's own thread. Unlike a
        global Ctrl+V, this targets *this exact* hwnd, so there's no focus race
        (the earlier approach could paste a field into the previously-focused box
        if ``SetFocus`` hadn't settled), no clipboard contention between fields,
        and no dependence on the window being foreground.
        """
        win32gui.SendMessage(hwnd, _EM_SETSEL, 0, -1)
        win32gui.SendMessage(hwnd, _EM_REPLACESEL, 1, text)

    def _paste_calibrated(self, parent_hwnd, section_fields, calibration) -> bool:
        """Place each ``(section, text)`` straight into its calibrated box.

        Resolves *every* box first; if any can't be resolved (or isn't calibrated),
        or if two boxes resolve to the *same* control, it returns False without
        writing anything -- so the caller can fall back to a safe single-block paste
        rather than scatter a half-placed note or let one box overwrite another.
        """
        resolved = []
        seen = {}
        for section, text in section_fields:
            box = calibration.get(section)
            if box is None:
                logger.warning("calibrated paste aborted: no calibration for %r", section)
                return False
            hwnd = self.resolve_calibration_box(parent_hwnd, box)
            if hwnd is None:
                logger.warning("calibrated paste aborted: could not resolve %r box", section)
                return False
            if hwnd in seen:
                logger.warning(
                    "calibrated paste aborted: %r and %r resolved to the same control "
                    "(%s) -- stale calibration",
                    seen[hwnd],
                    section,
                    hwnd,
                )
                return False
            seen[hwnd] = section
            resolved.append((section, hwnd, text))

        for section, hwnd, text in resolved:
            self._set_control_text(hwnd, text)
            logger.debug("calibrated paste: %d chars into %r box (control %s)", len(text), section, hwnd)
        logger.info("SOAP note injected into AVImark across %d calibrated boxes", len(resolved))
        return True

    def inject_fields_calibrated(self, section_fields, calibration) -> bool:
        """Calibrated counterpart of ``inject``: paste per box into the foreground.

        Requires AVImark to already be the foreground window (same guard as
        ``inject``). Returns False if the window isn't AVImark or a box can't be
        resolved -- the caller then falls back to the single-block paste.
        """
        if not self.is_avimark_foreground():
            logger.warning("calibrated injection skipped: AVImark is not the foreground window")
            return False
        parent_hwnd = win32gui.GetForegroundWindow()
        return self._paste_calibrated(parent_hwnd, section_fields, calibration)

    def focus_and_inject_fields_calibrated(
        self, section_fields, calibration, fallback_text: str
    ) -> bool:
        """Calibrated counterpart of ``focus_and_inject`` for the flyout/history.

        Resolves and raises the AVImark chart (same safety + ambiguity refusal),
        then pastes each section into its box. If the boxes can't be resolved, it
        still gets the note in -- as one block into the focused box -- using
        ``fallback_text``, so a stale calibration degrades gracefully instead of
        dropping the note.
        """
        hwnd = self._resolve_and_focus_target(fallback_text)
        if hwnd is None:
            return False
        if not self._paste_calibrated(hwnd, section_fields, calibration):
            logger.info("calibrated paste unavailable; falling back to single-block paste")
            self.copy_to_clipboard(fallback_text)
            self._send_ctrl_v()
        return True

    def _send_ctrl_v(self):
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord("V"), 0, 0, 0)
        win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
