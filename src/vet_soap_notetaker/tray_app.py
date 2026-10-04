import logging

import pystray
from PIL import Image

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.icon_art import render_logo
from vet_soap_notetaker.pipeline import PipelineState

logger = logging.getLogger("vet_soap_notetaker.tray_app")

ICON_SIZE = 64

STATE_COLORS = {
    PipelineState.IDLE: "green",
    PipelineState.RECORDING: "red",
    PipelineState.PROCESSING: "yellow",
}


def build_icon_image(color: str) -> Image.Image:
    # The cute-dog logo with a state-coloured collar: the collar tells the vet
    # at a glance whether the app is idle (green), recording (red) or
    # processing (yellow).
    return render_logo(ICON_SIZE, color)


class TrayApp:
    def __init__(
        self,
        pipeline,
        on_open_settings=None,
        on_show_note=None,
        on_show_history=None,
        on_calibrate=None,
    ):
        self.pipeline = pipeline
        self.hotkey_listener = None
        self.offline_queue = None
        self.injection_poller = None
        self.backend_supervisor = None
        self.tk_root = None
        self.on_open_settings = on_open_settings or (lambda: None)
        self.on_show_note = on_show_note or (lambda soap_text: None)
        self.on_show_history = on_show_history or (lambda: None)
        self.on_calibrate = on_calibrate or (lambda: None)
        self.icon = pystray.Icon(
            "vet_soap_notetaker",
            icon=build_icon_image(STATE_COLORS[PipelineState.IDLE]),
            title="Vet Soap Notetaker Assistant",
            menu=self._build_menu(),
        )

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(self._status_text, None, enabled=False),
            pystray.MenuItem(
                ui_strings.MENU_OPEN_LAST_SOAP_NOTE,
                lambda icon, item: self.open_last_note(),
                enabled=lambda item: self.pipeline.last_soap_text is not None,
            ),
            pystray.MenuItem(
                ui_strings.MENU_VIEW_HISTORY, lambda icon, item: self.show_history()
            ),
            pystray.MenuItem(
                ui_strings.MENU_SETTINGS, lambda icon, item: self.open_settings()
            ),
            pystray.MenuItem(
                ui_strings.MENU_CALIBRATE_AVIMARK, lambda icon, item: self.calibrate()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(ui_strings.MENU_QUIT, lambda icon, item: self.quit()),
        )

    def _status_text(self, item):
        return f"Status: {self.pipeline.state.value.capitalize()}"

    def attach_hotkey_listener(self, hotkey_listener):
        self.hotkey_listener = hotkey_listener

    def attach_offline_queue(self, offline_queue):
        self.offline_queue = offline_queue

    def attach_injection_poller(self, injection_poller):
        self.injection_poller = injection_poller

    def attach_backend_supervisor(self, backend_supervisor):
        self.backend_supervisor = backend_supervisor

    def attach_tk_root(self, tk_root):
        self.tk_root = tk_root

    def update_icon_for_state(self):
        self.icon.icon = build_icon_image(STATE_COLORS[self.pipeline.state])
        # pystray's win32 backend bakes each menu item's enabled/text state into
        # the native HMENU once, at construction (or the last update_menu()
        # call) -- it does not re-evaluate the enabled=/text= callables when the
        # menu is shown. Without this, "Open Last SOAP Note" stays frozen
        # disabled (its state when the tray icon was built, before any note
        # existed) even after a note is generated and the pipeline is back to
        # IDLE. Refresh it on every state transition so the menu reflects
        # last_soap_text and the current status text.
        self.icon.update_menu()

    def on_hotkey_triggered(self):
        previous_state = self.pipeline.state
        self.pipeline.toggle_recording()
        logger.info(
            "state transition: %s -> %s", previous_state.value, self.pipeline.state.value
        )
        self.update_icon_for_state()

    def open_last_note(self):
        if self.pipeline.last_soap_text:
            self.on_show_note(self.pipeline.last_soap_text)

    def show_history(self):
        self.on_show_history()

    def open_settings(self):
        self.on_open_settings()

    def calibrate(self):
        self.on_calibrate()

    def quit(self):
        logger.info("shutting down")
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        if self.pipeline.state == PipelineState.RECORDING:
            self.pipeline.recorder.stop()
        if self.offline_queue is not None:
            self.offline_queue.stop()
        if self.injection_poller is not None:
            self.injection_poller.stop()
        # Stop the backend last: the pollers above talk to it, so shut them down
        # first, then bring the backend process down so we don't leave an orphan.
        if self.backend_supervisor is not None:
            self.backend_supervisor.stop()
        self.icon.stop()
        if self.tk_root is not None:
            self.tk_root.after(0, self.tk_root.quit)
