from unittest.mock import MagicMock

from vetscribe import ui_strings
from vetscribe.icon_art import STATUS_SAMPLE
from vetscribe.pipeline import PipelineState
from vetscribe.tray_app import TrayApp, build_icon_image


def _status_rgb(image):
    # The tray icon's state colour lives in the status disc (where the notepad
    # sits on the brand logo), not the dog-face centre, so sample the disc.
    # Downscaling the supersampled art nudges the swatch a few levels off the
    # exact fill, so callers compare with a tolerance rather than for equality.
    px = image.getpixel(
        (int(image.width * STATUS_SAMPLE[0]), int(image.height * STATUS_SAMPLE[1]))
    )
    return px[:3]


def _is_close(rgb, expected, tol=25):
    return all(abs(a - b) <= tol for a, b in zip(rgb, expected))


def test_build_icon_image_returns_image_of_requested_color():
    image = build_icon_image("green")

    assert _is_close(_status_rgb(image), (0, 128, 0))


def make_tray_app(**overrides):
    pipeline = MagicMock(state=PipelineState.IDLE)
    pipeline.configure_mock(**overrides)
    return TrayApp(pipeline=pipeline), pipeline


def test_update_icon_for_state_sets_icon_matching_recording_state():
    tray_app, pipeline = make_tray_app(state=PipelineState.RECORDING)

    tray_app.update_icon_for_state()

    assert _is_close(_status_rgb(tray_app.icon.icon), (255, 0, 0))


def test_update_icon_for_state_refreshes_native_menu():
    # Regression test: pystray's win32 backend bakes each menu item's
    # enabled/text state into the native menu once, at construction (or the
    # last update_menu() call) -- it does not re-evaluate the enabled=/text=
    # callables just because the menu is about to be shown. Without an
    # explicit update_menu() call on every state transition, "Open Last SOAP
    # Note" stays frozen disabled (its state when the tray icon was built,
    # before any note existed) even after a note is generated and the
    # pipeline goes back to IDLE.
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.icon.update_menu = MagicMock()

    tray_app.update_icon_for_state()

    tray_app.icon.update_menu.assert_called_once()


def test_on_hotkey_triggered_toggles_pipeline_and_refreshes_icon():
    tray_app, pipeline = make_tray_app(state=PipelineState.IDLE)

    def fake_toggle():
        pipeline.state = PipelineState.RECORDING

    pipeline.toggle_recording.side_effect = fake_toggle

    tray_app.on_hotkey_triggered()

    pipeline.toggle_recording.assert_called_once()
    assert _is_close(_status_rgb(tray_app.icon.icon), (255, 0, 0))


def test_menu_has_status_open_note_history_settings_separator_and_quit_items():
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)

    labels = [str(item) for item in tray_app.icon.menu.items]

    assert labels[0].startswith("Status:")
    assert labels[1] == ui_strings.MENU_OPEN_LAST_SOAP_NOTE
    assert labels[2] == ui_strings.MENU_VIEW_HISTORY
    assert labels[3] == ui_strings.MENU_SETTINGS
    assert labels[4] == ui_strings.MENU_CALIBRATE_AVIMARK
    assert labels[6] == ui_strings.MENU_QUIT


def test_calibrate_menu_item_invokes_on_calibrate():
    calls = []
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.on_calibrate = lambda: calls.append("calibrate")

    tray_app.calibrate()

    assert calls == ["calibrate"]


def test_view_history_menu_item_invokes_on_show_history():
    calls = []
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.on_show_history = lambda: calls.append("history")

    tray_app.show_history()

    assert calls == ["history"]


def test_status_menu_item_reflects_current_pipeline_state():
    tray_app, pipeline = make_tray_app(state=PipelineState.RECORDING)

    status_item = tray_app.icon.menu.items[0]

    assert status_item.text == "Status: Recording"
    assert status_item.enabled is False


def test_open_last_note_menu_item_disabled_when_no_note_yet():
    tray_app, pipeline = make_tray_app(state=PipelineState.IDLE, last_soap_text=None)

    open_note_item = tray_app.icon.menu.items[1]

    assert open_note_item.enabled is False


def test_open_last_note_invokes_on_show_note_with_last_soap_text():
    shown = []
    tray_app, pipeline = make_tray_app(state=PipelineState.IDLE, last_soap_text="SUBJECTIVE: text")
    tray_app.on_show_note = shown.append

    open_note_item = tray_app.icon.menu.items[1]
    assert open_note_item.enabled is True

    tray_app.open_last_note()

    assert shown == ["SUBJECTIVE: text"]


def test_open_settings_invokes_on_open_settings_callback():
    calls = []
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.on_open_settings = lambda: calls.append("opened")

    tray_app.open_settings()

    assert calls == ["opened"]


def test_quit_stops_hotkey_listener_stops_active_recording_and_stops_icon():
    tray_app, pipeline = make_tray_app(state=PipelineState.RECORDING)
    hotkey_listener = MagicMock()
    tray_app.attach_hotkey_listener(hotkey_listener)
    tray_app.icon.stop = MagicMock()

    tray_app.quit()

    hotkey_listener.stop.assert_called_once()
    pipeline.recorder.stop.assert_called_once()
    tray_app.icon.stop.assert_called_once()


def test_quit_does_not_stop_recorder_when_not_recording():
    tray_app, pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.icon.stop = MagicMock()

    tray_app.quit()

    pipeline.recorder.stop.assert_not_called()
    tray_app.icon.stop.assert_called_once()


def test_quit_stops_attached_offline_queue():
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.icon.stop = MagicMock()
    offline_queue = MagicMock()
    tray_app.attach_offline_queue(offline_queue)

    tray_app.quit()

    offline_queue.stop.assert_called_once()


def test_quit_without_attached_offline_queue_does_not_raise():
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.icon.stop = MagicMock()

    tray_app.quit()


def test_quit_stops_attached_injection_poller():
    tray_app, _pipeline = make_tray_app(state=PipelineState.IDLE)
    tray_app.icon.stop = MagicMock()
    injection_poller = MagicMock()
    tray_app.attach_injection_poller(injection_poller)

    tray_app.quit()

    injection_poller.stop.assert_called_once()
