"""Drive an on-site AVImark box calibration.

``CalibrationController`` sequences the one-time setup: prompt the vet to click in
each SOAP box, capture each click as a ``BoxControl``, and when all four are
captured, save the calibration and tear down. The instruction window and the
global mouse hook are injected as callables (``prompt`` / ``close`` and the caller
feeding ``on_click``) so this logic is testable without a display or pynput; the
real Tk window + ``pynput.mouse.Listener`` are wired in ``main.py``.
"""

import logging

from vet_soap_notetaker.avimark_calibration import CalibrationSession

logger = logging.getLogger("vet_soap_notetaker.calibration_ui")


def prompt_window_position(screen_width, screen_height, window_width, window_height, margin=24):
    """Top-left (x, y) to place the calibration prompt, in the bottom-right corner.

    The prompt must not sit on top of the AVImark note boxes the vet is about to
    click: when it does, the click-filter swallows those clicks and calibration
    silently freezes on that box (observed on a small laptop, where the prompt's
    undefined default position landed right over the Plan box). AVImark's note
    window -- and the mock -- live at the top-left, so the opposite corner keeps
    the prompt clear. Clamped to the origin so a prompt larger than the screen
    never ends up off-screen and unreachable. The maximized-AVImark case (where
    no corner is clear) is handled separately by the on-screen 'drag it aside'
    warning.
    """
    x = max(0, screen_width - window_width - margin)
    y = max(0, screen_height - window_height - margin)
    return (x, y)


class CalibrationController:
    def __init__(self, capture, save, prompt, close, warn=None, invalid=None):
        """
        capture(x, y) -> BoxControl : identify the control under a click
        save(BoxCalibration)        : persist the finished calibration (go live)
        prompt(section, done, total): show/update the instruction for the next box
        close()                     : tear down the prompt window + mouse hook
        warn()                      : tell the vet a click landed on the prompt
                                      window (covering the box); optional.
        invalid()                   : tell the vet the capture collapsed (all boxes
                                      hit one control) and to start over; optional.
        """
        self._capture = capture
        self._session = CalibrationSession(capture_fn=capture)
        self._save = save
        self._prompt = prompt
        self._close = close
        self._warn = warn or (lambda: None)
        self._invalid = invalid or (lambda: None)

    def start(self):
        section = self._session.current_section
        done, total = self._session.progress
        logger.info("calibration started; first box: %s", section)
        self._prompt(section, done, total)

    def on_click_on_prompt(self):
        """Report a calibration click that landed on our own instruction window.

        Such a click isn't an AVImark box, so it must not be captured -- but it
        must not be *silently* dropped either: that's what made calibration look
        frozen when the prompt window happened to cover a box. Surfacing it (the
        window is draggable, so the remedy is to move it aside) turns a dead-end
        into something recoverable. Ignored once calibration is complete, since
        the prompt window is gone by then.
        """
        if self._session.is_complete():
            return
        logger.info("calibration click landed on the prompt window; warning the vet")
        self._warn()

    def on_click(self, screen_x, screen_y):
        """Feed one committed click. Ignored once calibration is complete."""
        if self._session.is_complete():
            return
        section = self._session.record_click(screen_x, screen_y)
        logger.info("captured %s box at (%s, %s)", section, screen_x, screen_y)
        if self._session.is_complete():
            result = self._session.result()
            if result.has_duplicate_controls():
                # The capture collapsed (every box resolved to one control -- the
                # multi-monitor DPI bug). Don't persist a calibration that would
                # paste the whole note into one box; tell the vet and start over.
                logger.warning(
                    "calibration captured duplicate controls; discarding and restarting"
                )
                self._session = CalibrationSession(capture_fn=self._capture)
                self._invalid()
                return
            self._save(result)
            logger.info("calibration complete; saved all four boxes")
            self._close()
        else:
            next_section = self._session.current_section
            done, total = self._session.progress
            self._prompt(next_section, done, total)
