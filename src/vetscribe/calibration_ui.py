"""Drive an on-site AVImark box calibration.

``CalibrationController`` sequences the one-time setup: prompt the vet to click in
each SOAP box, capture each click as a ``BoxControl``, and when all four are
captured, save the calibration and tear down. The instruction window and the
global mouse hook are injected as callables (``prompt`` / ``close`` and the caller
feeding ``on_click``) so this logic is testable without a display or pynput; the
real Tk window + ``pynput.mouse.Listener`` are wired in ``main.py``.
"""

import logging

from vetscribe.avimark_calibration import CalibrationSession

logger = logging.getLogger("vetscribe.calibration_ui")


class CalibrationController:
    def __init__(self, capture, save, prompt, close):
        """
        capture(x, y) -> BoxControl : identify the control under a click
        save(BoxCalibration)        : persist the finished calibration (go live)
        prompt(section, done, total): show/update the instruction for the next box
        close()                     : tear down the prompt window + mouse hook
        """
        self._session = CalibrationSession(capture_fn=capture)
        self._save = save
        self._prompt = prompt
        self._close = close

    def start(self):
        section = self._session.current_section
        done, total = self._session.progress
        logger.info("calibration started; first box: %s", section)
        self._prompt(section, done, total)

    def on_click(self, screen_x, screen_y):
        """Feed one committed click. Ignored once calibration is complete."""
        if self._session.is_complete():
            return
        section = self._session.record_click(screen_x, screen_y)
        logger.info("captured %s box at (%s, %s)", section, screen_x, screen_y)
        if self._session.is_complete():
            self._save(self._session.result())
            logger.info("calibration complete; saved all four boxes")
            self._close()
        else:
            next_section = self._session.current_section
            done, total = self._session.progress
            self._prompt(next_section, done, total)
