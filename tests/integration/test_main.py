import threading
import time
from dataclasses import replace
from unittest.mock import MagicMock

from vet_soap_notetaker.api_client import ApiClient, Exam, SoapNote
from vet_soap_notetaker.audio_recorder import AudioRecorder
from vet_soap_notetaker.avimark_injector import AvimarkInjector
from vet_soap_notetaker.config import Config
from vet_soap_notetaker.icon_art import STATUS_SAMPLE
from vet_soap_notetaker.main import build_app, follow_active_avimark
from vet_soap_notetaker.pipeline import PipelineState


def test_follow_active_avimark_tracks_until_window_closes():
    tk_root = MagicMock()
    injector = MagicMock()
    window = MagicMock()
    # winfo_exists: still open on the first tick, gone on the second.
    window.winfo_exists.side_effect = [True, False]

    follow_active_avimark(tk_root, injector, window, interval_ms=10)

    # The loop arms itself on the Tk event loop rather than running inline.
    tk_root.after.assert_called_once()
    injector.track_active_window.assert_not_called()

    # Fire the first scheduled tick: window is open, so re-capture and re-arm.
    _, first_tick = tk_root.after.call_args[0]
    first_tick()
    injector.track_active_window.assert_called_once()
    assert tk_root.after.call_count == 2

    # Fire the second tick: window is gone, so stop -- no further tracking.
    _, second_tick = tk_root.after.call_args[0]
    second_tick()
    injector.track_active_window.assert_called_once()
    assert tk_root.after.call_count == 2


def test_build_app_wires_pipeline_dependencies_from_config():
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
        api_key="secret-token",
        target_window_matcher="PracticeSoft",
    )
    tk_root = MagicMock()

    tray_app, hotkey_listener, returned_root = build_app(config=config, tk_root=tk_root)

    pipeline = tray_app.pipeline
    assert isinstance(pipeline.recorder, AudioRecorder)
    assert isinstance(pipeline.api_client, ApiClient)
    assert pipeline.api_client.endpoint == "https://example.test/soap"
    assert pipeline.api_client.timeout_seconds == 15
    assert pipeline.api_client.api_key == "secret-token"
    assert isinstance(pipeline.injector, AvimarkInjector)
    assert pipeline.injector.title_marker == "PracticeSoft"
    assert returned_root is tk_root
    tk_root.withdraw.assert_called_once()


def test_tray_icon_turns_yellow_while_backend_call_is_in_flight():
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    pipeline = tray_app.pipeline
    pipeline.recorder = MagicMock(save_wav=lambda path: path.write_bytes(b"wav"))
    pipeline.injector = MagicMock(inject=MagicMock(return_value=True))

    observed_color_mid_call = {}

    def fake_generate_soap_note(_audio_bytes):
        icon = tray_app.icon.icon
        observed_color_mid_call["value"] = icon.getpixel(
            (int(icon.width * STATUS_SAMPLE[0]), int(icon.height * STATUS_SAMPLE[1]))
        )
        raise AssertionError("stop before real network/injection work")

    pipeline.api_client = MagicMock(generate_soap_note=fake_generate_soap_note)
    pipeline.state = PipelineState.RECORDING

    try:
        pipeline.toggle_recording()
    except AssertionError:
        pass

    # The processing state shows as a yellow status disc on the dog logo.
    r, g, b = observed_color_mid_call["value"][:3]
    assert r > 200 and g > 200 and b < 60


def test_build_app_wires_hotkey_listener_to_tray_app_trigger():
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, hotkey_listener, _ = build_app(config=config, tk_root=tk_root)
    triggered = threading.Event()
    tray_app.on_hotkey_triggered = triggered.set

    hotkey_listener.on_trigger()

    assert triggered.wait(timeout=1)
    assert tray_app.hotkey_listener is hotkey_listener


def test_build_app_hotkey_trigger_returns_immediately_even_when_pipeline_is_slow():
    # Regression test: the hotkey listener's on_trigger callback fires on the
    # OS-level global keyboard hook thread. If it blocks for as long as the
    # pipeline takes (a real backend call), Windows stalls keyboard delivery
    # system-wide and replays queued keypresses once it returns -- which can
    # re-fire the hotkey without the user actively holding it down. The
    # callback build_app wires up must therefore return near-instantly.
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, hotkey_listener, _ = build_app(config=config, tk_root=tk_root)
    started = threading.Event()
    release_worker = threading.Event()

    def slow_on_hotkey_triggered():
        started.set()
        release_worker.wait(timeout=1)

    tray_app.on_hotkey_triggered = slow_on_hotkey_triggered

    start = time.monotonic()
    hotkey_listener.on_trigger()
    elapsed = time.monotonic() - start

    assert started.wait(timeout=1)
    assert elapsed < 0.1
    release_worker.set()


def test_build_app_wires_configured_hotkey_into_hotkey_listener():
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<alt>+v",
    )
    tk_root = MagicMock()

    _tray_app, hotkey_listener, _ = build_app(config=config, tk_root=tk_root)

    assert hotkey_listener.hotkey == "<ctrl>+<alt>+v"


def test_build_app_flyout_callback_creates_flyout_window_on_injection_failure(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    pipeline = tray_app.pipeline

    pipeline.on_flyout_needed("SUBJECTIVE: text")

    mock_flyout_cls.assert_called_once()
    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["master"] is tk_root
    assert kwargs["soap_text"] == "SUBJECTIVE: text"


def test_build_app_error_callback_shows_flyout_with_error_message(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    pipeline = tray_app.pipeline

    pipeline.on_error("SOAP Generation Failed: backend unreachable.")

    mock_flyout_cls.assert_called_once()
    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["master"] is tk_root
    assert kwargs["soap_text"] == "SOAP Generation Failed: backend unreachable."


def test_note_flyout_offers_open_history_that_opens_the_history_window(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    mock_history_cls = mocker.patch("vet_soap_notetaker.main.HistoryWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    tray_app.pipeline.on_flyout_needed("SUBJECTIVE: text")

    _, kwargs = mock_flyout_cls.call_args
    open_history = kwargs["on_open_history"]
    assert open_history is not None
    # Clicking it brings the vet to the full history window.
    open_history()
    mock_history_cls.assert_called_once()


def test_error_flyout_has_no_open_history_button(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    tray_app.pipeline.on_error("SOAP Generation Failed: backend unreachable.")

    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["on_open_history"] is None


def test_open_last_note_shows_flyout_with_last_soap_text(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    tray_app.pipeline.last_soap_text = "SUBJECTIVE: last note"

    tray_app.open_last_note()

    mock_flyout_cls.assert_called_once()
    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["master"] is tk_root
    assert kwargs["soap_text"] == "SUBJECTIVE: last note"


def test_open_settings_opens_settings_window_with_current_config(mocker):
    mock_settings_cls = mocker.patch("vet_soap_notetaker.main.SettingsWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    tray_app.open_settings()

    mock_settings_cls.assert_called_once()
    _, kwargs = mock_settings_cls.call_args
    assert kwargs["master"] is tk_root
    assert kwargs["config"] is config


def test_open_settings_from_tray_thread_is_marshalled_onto_main_thread(mocker):
    # The tray menu fires on the pystray icon thread. Constructing the Tk
    # SettingsWindow directly from a background thread deadlocks (no traceback);
    # it must be marshalled via tk_root.after, exactly like history/note.
    mock_settings_cls = mocker.patch("vet_soap_notetaker.main.SettingsWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)

    def click_from_tray_thread():
        tray_app.open_settings()

    t = threading.Thread(target=click_from_tray_thread)
    t.start()
    t.join()

    # Off the main thread, the window must NOT be built inline; the work is
    # handed to the Tk event loop instead.
    mock_settings_cls.assert_not_called()
    tk_root.after.assert_called_once()
    assert tk_root.after.call_args.args[0] == 0


def test_saving_settings_persists_config_and_updates_live_components(mocker, tmp_path):
    mock_settings_cls = mocker.patch("vet_soap_notetaker.main.SettingsWindow")
    mocker.patch("vet_soap_notetaker.main.autostart")
    mocker.patch("vet_soap_notetaker.hotkey_listener.keyboard.Listener")
    config_path = tmp_path / "config.json"
    mocker.patch("vet_soap_notetaker.main.CONFIG_PATH", config_path)
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
        api_key="old-key",
        target_window_matcher="AVImark",
    )
    tk_root = MagicMock()

    tray_app, hotkey_listener, _ = build_app(config=config, tk_root=tk_root)
    hotkey_listener.start()
    tray_app.open_settings()

    _, kwargs = mock_settings_cls.call_args
    apply_settings = kwargs["on_save"]

    new_config = Config(
        api_endpoint="https://new.example.test/soap",
        api_timeout_seconds=45,
        hotkey="<ctrl>+<alt>+v",
        api_key="new-key",
        target_window_matcher="PracticeSoft",
    )
    apply_settings(new_config)

    pipeline = tray_app.pipeline
    assert pipeline.api_client.endpoint == "https://new.example.test/soap"
    assert pipeline.api_client.timeout_seconds == 45
    assert pipeline.api_client.api_key == "new-key"
    assert pipeline.injector.title_marker == "PracticeSoft"
    assert hotkey_listener.hotkey == "<ctrl>+<alt>+v"

    reloaded = Config.load(config_path)
    assert reloaded.api_endpoint == "https://new.example.test/soap"
    assert reloaded.hotkey == "<ctrl>+<alt>+v"


def test_saving_settings_enables_autostart_when_launch_on_startup_checked(mocker, tmp_path):
    mock_settings_cls = mocker.patch("vet_soap_notetaker.main.SettingsWindow")
    mock_enable = mocker.patch("vet_soap_notetaker.main.autostart.enable")
    mock_disable = mocker.patch("vet_soap_notetaker.main.autostart.disable")
    mocker.patch("vet_soap_notetaker.hotkey_listener.keyboard.Listener")
    mocker.patch("vet_soap_notetaker.main.CONFIG_PATH", tmp_path / "config.json")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, hotkey_listener, _ = build_app(config=config, tk_root=tk_root)
    hotkey_listener.start()
    tray_app.open_settings()
    apply_settings = mock_settings_cls.call_args.kwargs["on_save"]

    apply_settings(replace(config, launch_on_startup=True))
    mock_enable.assert_called_once()
    mock_disable.assert_not_called()

    apply_settings(replace(config, launch_on_startup=False))
    mock_disable.assert_called_once()


def test_build_app_wires_offline_queue_into_pipeline_and_tray_app():
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)

    assert tray_app.offline_queue is tray_app.pipeline.offline_queue
    assert tray_app.offline_queue.api_client is tray_app.pipeline.api_client


def test_view_history_opens_window_reading_the_shared_backend_history(mocker, tmp_path):
    # The history the user browses is the backend's shared exam store -- the same
    # records the mobile app reads -- so opening the window surfaces every note,
    # whether it was recorded on this desktop or on a phone.
    mock_history_window = mocker.patch("vet_soap_notetaker.main.HistoryWindow")
    mocker.patch(
        "vet_soap_notetaker.backend_history_store.get_cache_path",
        return_value=tmp_path / "history_cache.json",
    )
    exams = [
        Exam(
            id="e1",
            created_at="2026-09-22T00:00:01Z",
            subjective="from the backend",
            objective="o",
            assessment="a",
            plan="p",
            transcript="tx",
        )
    ]
    mocker.patch.object(ApiClient, "fetch_history", return_value=exams)
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    tray_app.show_history()

    mock_history_window.assert_called_once()
    _, kwargs = mock_history_window.call_args
    assert kwargs["master"] is tk_root
    # The window is handed a callable that reads the shared backend history live,
    # so calling it surfaces the exams the backend serves.
    entries = kwargs["load_entries"]()
    assert [entry.subjective for entry in entries] == ["from the backend"]

    # The window's save callback persists a structured edit back through the
    # backend, so it syncs to every device.
    update_mock = mocker.patch.object(
        ApiClient,
        "update_exam",
        return_value=Exam(
            id="e1",
            created_at="2026-09-22T00:00:01Z",
            subjective="edited",
            objective="o",
            assessment="a",
            plan="p",
            transcript="edited transcript",
        ),
    )
    kwargs["on_save_edit"](
        "e1",
        subjective="edited",
        objective="o",
        assessment="a",
        plan="p",
        transcript="edited transcript",
    )
    update_mock.assert_called_once_with(
        "e1",
        subjective="edited",
        objective="o",
        assessment="a",
        plan="p",
        transcript="edited transcript",
    )

    # The window's delete callback removes the note through the backend.
    delete_mock = mocker.patch.object(ApiClient, "delete_exam")
    kwargs["on_delete"]("e1")
    delete_mock.assert_called_once_with("e1")


def test_build_app_wires_injection_poller_to_api_client_and_tray_app():
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)

    assert tray_app.injection_poller is not None
    assert tray_app.injection_poller.api_client is tray_app.pipeline.api_client


def _injection_request():
    return {
        "id": "req-1",
        "exam_id": "exam-1",
        "exam": {
            "subjective": "s",
            "objective": "o",
            "assessment": "a",
            "plan": "p",
            "transcript": "t",
        },
    }


_EXPECTED_NOTE = "SUBJECTIVE: s\nOBJECTIVE: o\nASSESSMENT: a\nPLAN: p"


def test_remote_injection_pastes_into_avimark_and_skips_flyout_when_targetable(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    inject = mocker.patch.object(
        tray_app.pipeline.injector, "focus_and_inject", return_value=True
    )

    tray_app.injection_poller.on_injection(_injection_request())

    # The note is pasted straight into the AVImark chart; no flyout needed.
    inject.assert_called_once_with(_EXPECTED_NOTE)
    mock_flyout_cls.assert_not_called()


def test_remote_injection_falls_back_to_safety_flyout_when_not_targetable(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    mocker.patch.object(
        tray_app.pipeline.injector, "focus_and_inject", return_value=False
    )

    tray_app.injection_poller.on_injection(_injection_request())

    # AVImark wasn't safely targetable, so the note surfaces in the Safety Flyout
    # with the same text, ready for a manual Copy & Inject.
    mock_flyout_cls.assert_called_once()
    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["master"] is tk_root
    assert kwargs["soap_text"] == _EXPECTED_NOTE


def test_build_app_offline_queue_on_note_ready_shows_flyout(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    tray_app.offline_queue.on_note_ready("SUBJECTIVE: recovered note")

    mock_flyout_cls.assert_called_once()
    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["master"] is tk_root
    assert kwargs["soap_text"] == "SUBJECTIVE: recovered note"


def _calibration_dict():
    sections = ("subjective", "objective", "assessment", "plan")
    return {
        s: {"control_id": 1000 + i, "class_name": "Edit", "rel_x": 0.1, "rel_y": 0.1 * i}
        for i, s in enumerate(sections)
    }


def test_remote_injection_uses_calibrated_per_box_paste_when_calibrated(mocker):
    from vet_soap_notetaker.avimark_calibration import BoxCalibration

    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
        avimark_calibration=_calibration_dict(),
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    calibrated = mocker.patch.object(
        tray_app.pipeline.injector, "focus_and_inject_fields_calibrated", return_value=True
    )
    plain = mocker.patch.object(tray_app.pipeline.injector, "focus_and_inject")

    tray_app.injection_poller.on_injection(_injection_request())

    plain.assert_not_called()
    calibrated.assert_called_once()
    args = calibrated.call_args.args
    assert args[0] == [
        ("subjective", "s"),
        ("objective", "o"),
        ("assessment", "a"),
        ("plan", "p"),
    ]
    assert isinstance(args[1], BoxCalibration)
    assert args[2] == _EXPECTED_NOTE  # single-block fallback text
    mock_flyout_cls.assert_not_called()


def test_remote_injection_calibrated_failure_falls_back_to_flyout(mocker):
    mock_flyout_cls = mocker.patch("vet_soap_notetaker.main.FlyoutWindow")
    config = Config(
        api_endpoint="https://example.test/soap",
        api_timeout_seconds=15,
        hotkey="<ctrl>+<shift>+r",
        avimark_calibration=_calibration_dict(),
    )
    tk_root = MagicMock()

    tray_app, _, _ = build_app(config=config, tk_root=tk_root)
    mocker.patch.object(
        tray_app.pipeline.injector,
        "focus_and_inject_fields_calibrated",
        return_value=False,
    )

    tray_app.injection_poller.on_injection(_injection_request())

    mock_flyout_cls.assert_called_once()
    _, kwargs = mock_flyout_cls.call_args
    assert kwargs["soap_text"] == _EXPECTED_NOTE
