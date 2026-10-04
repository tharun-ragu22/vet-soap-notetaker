from unittest.mock import MagicMock

from vet_soap_notetaker.api_client import ApiClientError, SoapNote
from vet_soap_notetaker.pipeline import Pipeline, PipelineState


def make_pipeline(**overrides):
    defaults = dict(
        recorder=MagicMock(),
        api_client=MagicMock(),
        injector=MagicMock(),
        on_flyout_needed=MagicMock(),
    )
    defaults.update(overrides)
    return Pipeline(**defaults), defaults


def test_toggle_recording_from_idle_starts_recording():
    pipeline, deps = make_pipeline()

    pipeline.toggle_recording()

    deps["recorder"].start.assert_called_once()
    assert pipeline.state == PipelineState.RECORDING


def test_toggle_recording_from_recording_stops_and_injects_successfully():
    soap_note = SoapNote(
        subjective="sub", objective="obj", assessment="assess", plan="plan"
    )
    recorder = MagicMock(
        save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"fake-wav"))
    )
    deps_overrides = dict(
        recorder=recorder,
        api_client=MagicMock(generate_soap_note=MagicMock(return_value=soap_note)),
        injector=MagicMock(inject=MagicMock(return_value=True)),
    )
    pipeline, deps = make_pipeline(**deps_overrides)
    pipeline.state = PipelineState.RECORDING

    pipeline.toggle_recording()

    deps["recorder"].stop.assert_called_once()
    deps["recorder"].save_wav.assert_called_once()
    deps["api_client"].generate_soap_note.assert_called_once()
    deps["injector"].inject.assert_called_once()
    deps["on_flyout_needed"].assert_not_called()
    assert pipeline.state == PipelineState.IDLE


def test_toggle_recording_from_recording_calls_flyout_when_injection_fails():
    soap_note = SoapNote(
        subjective="sub", objective="obj", assessment="assess", plan="plan"
    )
    recorder = MagicMock(
        save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"fake-wav"))
    )
    deps_overrides = dict(
        recorder=recorder,
        api_client=MagicMock(generate_soap_note=MagicMock(return_value=soap_note)),
        injector=MagicMock(inject=MagicMock(return_value=False)),
    )
    pipeline, deps = make_pipeline(**deps_overrides)
    pipeline.state = PipelineState.RECORDING

    pipeline.toggle_recording()

    deps["on_flyout_needed"].assert_called_once()
    called_text = deps["on_flyout_needed"].call_args[0][0]
    assert "SUBJECTIVE: sub" in called_text
    assert "PLAN: plan" in called_text
    assert pipeline.state == PipelineState.IDLE


def test_toggle_recording_is_noop_while_processing():
    pipeline, deps = make_pipeline()
    pipeline.state = PipelineState.PROCESSING

    pipeline.toggle_recording()

    deps["recorder"].start.assert_not_called()
    deps["recorder"].stop.assert_not_called()
    assert pipeline.state == PipelineState.PROCESSING


def test_toggle_recording_saves_audio_and_reports_error_when_backend_fails(tmp_path):
    recorder = MagicMock(
        save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"fake-wav-bytes"))
    )
    on_error = MagicMock()
    recordings_dir = tmp_path / "recordings"
    deps_overrides = dict(
        recorder=recorder,
        api_client=MagicMock(
            generate_soap_note=MagicMock(
                side_effect=ApiClientError("backend unreachable")
            )
        ),
        on_error=on_error,
        recordings_dir=recordings_dir,
    )
    pipeline, deps = make_pipeline(**deps_overrides)
    pipeline.state = PipelineState.RECORDING

    pipeline.toggle_recording()

    deps["recorder"].stop.assert_called_once()
    deps["injector"].inject.assert_not_called()
    deps["on_flyout_needed"].assert_not_called()
    on_error.assert_called_once()
    message = on_error.call_args[0][0]
    assert "backend unreachable" in message
    assert pipeline.state == PipelineState.IDLE

    saved_files = list(recordings_dir.glob("failed_*.wav"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"fake-wav-bytes"
    assert str(saved_files[0]) in message


def test_toggle_recording_enqueues_audio_to_offline_queue_on_backend_failure(tmp_path):
    recorder = MagicMock(
        save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"fake-wav-bytes"))
    )
    offline_queue = MagicMock()
    deps_overrides = dict(
        recorder=recorder,
        api_client=MagicMock(
            generate_soap_note=MagicMock(side_effect=ApiClientError("backend unreachable"))
        ),
        recordings_dir=tmp_path / "recordings",
        offline_queue=offline_queue,
    )
    pipeline, deps = make_pipeline(**deps_overrides)
    pipeline.state = PipelineState.RECORDING

    pipeline.toggle_recording()

    offline_queue.enqueue.assert_called_once_with(b"fake-wav-bytes")
    assert pipeline.state == PipelineState.IDLE


def test_toggle_recording_reports_every_state_transition_via_on_state_change():
    soap_note = SoapNote(
        subjective="sub", objective="obj", assessment="assess", plan="plan"
    )
    recorder = MagicMock(
        save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"fake-wav"))
    )
    on_state_change = MagicMock()
    deps_overrides = dict(
        recorder=recorder,
        api_client=MagicMock(generate_soap_note=MagicMock(return_value=soap_note)),
        injector=MagicMock(inject=MagicMock(return_value=True)),
        on_state_change=on_state_change,
    )
    pipeline, deps = make_pipeline(**deps_overrides)

    pipeline.toggle_recording()
    pipeline.toggle_recording()

    assert [call.args[0] for call in on_state_change.call_args_list] == [
        PipelineState.RECORDING,
        PipelineState.PROCESSING,
        PipelineState.IDLE,
    ]


def test_toggle_recording_does_not_crash_when_on_error_not_provided(tmp_path):
    recorder = MagicMock(
        save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"fake-wav-bytes"))
    )
    deps_overrides = dict(
        recorder=recorder,
        api_client=MagicMock(
            generate_soap_note=MagicMock(side_effect=ApiClientError("timed out"))
        ),
        recordings_dir=tmp_path / "recordings",
    )
    pipeline, deps = make_pipeline(**deps_overrides)
    pipeline.state = PipelineState.RECORDING

    pipeline.toggle_recording()

    assert pipeline.state == PipelineState.IDLE
