"""What the hotkey pipeline reports to analytics: recording length, how long
the vet waited for the note, failures, busy presses, and how the note landed."""

from unittest.mock import MagicMock

from tests.fakes import RecordingAnalytics
from vet_soap_notetaker.api_client import (
    ApiClientError,
    BackendUnreachableError,
    NotePendingError,
    SoapNote,
)
from vet_soap_notetaker.pipeline import Pipeline, PipelineState


class Clock:
    def __init__(self, *times):
        self.times = list(times)

    def __call__(self):
        return self.times.pop(0)


def _pipeline(tmp_path, api_client, clock, injector=None, **overrides):
    tracker = RecordingAnalytics()
    recorder = MagicMock(save_wav=MagicMock(side_effect=lambda path: path.write_bytes(b"wav")))
    deps = dict(
        recorder=recorder,
        api_client=api_client,
        injector=injector or MagicMock(inject=MagicMock(return_value=True), last_result="single_block"),
        on_flyout_needed=MagicMock(),
        on_error=MagicMock(),
        recordings_dir=tmp_path / "recordings",
        offline_queue=MagicMock(),
        analytics=tracker,
        clock=clock,
    )
    deps.update(overrides)
    return Pipeline(**deps), tracker, deps


def _note():
    return SoapNote("s", "o", "a", "p", exam_id="exam-7")


def test_a_recorded_note_reports_recording_length_wait_and_how_it_landed(tmp_path):
    api_client = MagicMock(generate_soap_note=MagicMock(return_value=_note()))
    # start, stop, note back
    pipeline, tracker, _ = _pipeline(tmp_path, api_client, Clock(100.0, 130.0, 134.5))

    pipeline.toggle_recording()
    pipeline.toggle_recording()

    assert [e["event"] for e in tracker.events] == [
        "recording_started",
        "recording_stopped",
        "note_ready",
        "injection_completed",
    ]
    assert tracker.only("recording_stopped")["properties"] == {"recording_ms": 30000}
    assert tracker.only("note_ready")["properties"] == {
        "exam_id": "exam-7",
        "wait_ms": 4500,
        "recording_ms": 30000,
        "via_offline_queue": False,
    }
    assert tracker.only("injection_completed")["properties"] == {
        "source": "hotkey",
        "exam_id": "exam-7",
        "result": "single_block",
        "fallback_flyout_shown": False,
    }
    # The backend gets the recording length for its own timing analytics.
    assert api_client.generate_soap_note.call_args.kwargs == {"audio_duration_ms": 30000}


def test_a_refused_inject_reports_the_fallback_flyout(tmp_path):
    api_client = MagicMock(generate_soap_note=MagicMock(return_value=_note()))
    injector = MagicMock(inject=MagicMock(return_value=False), last_result="refused_not_foreground")
    pipeline, tracker, _ = _pipeline(
        tmp_path, api_client, Clock(0.0, 1.0, 2.0), injector=injector
    )

    pipeline.toggle_recording()
    pipeline.toggle_recording()

    props = tracker.only("injection_completed")["properties"]
    assert props["result"] == "refused_not_foreground"
    assert props["fallback_flyout_shown"] is True


def _fail_with(tmp_path, error, **overrides):
    api_client = MagicMock(generate_soap_note=MagicMock(side_effect=error))
    pipeline, tracker, _ = _pipeline(tmp_path, api_client, Clock(0.0, 10.0, 12.0), **overrides)
    pipeline.toggle_recording()
    pipeline.toggle_recording()
    assert pipeline.state == PipelineState.IDLE
    return tracker


def test_a_note_pending_reply_is_reported(tmp_path):
    tracker = _fail_with(tmp_path, NotePendingError("exam-7"))

    assert tracker.only("note_failed")["properties"] == {
        "outcome": "note_pending",
        "error_type": "NotePendingError",
        "exam_id": "exam-7",
        "wait_ms": 2000,
        "recording_ms": 10000,
        "queued": True,
    }
    assert tracker.named("note_ready") == []


def test_an_unreachable_backend_is_reported(tmp_path):
    props = _fail_with(tmp_path, BackendUnreachableError("down"))
    assert props.only("note_failed")["properties"]["outcome"] == "backend_unreachable"


def test_a_backend_error_is_reported_without_its_message(tmp_path):
    tracker = _fail_with(
        tmp_path, ApiClientError("backend returned 502: ZZ_PATIENT_SENTINEL"), offline_queue=None
    )

    props = tracker.only("note_failed")["properties"]
    assert props["outcome"] == "backend_error"
    assert props["error_type"] == "ApiClientError"
    assert props["queued"] is False
    assert "ZZ_PATIENT_SENTINEL" not in repr(tracker.events)


def test_a_hotkey_press_while_busy_is_reported(tmp_path):
    pipeline, tracker, _ = _pipeline(tmp_path, MagicMock(), Clock())
    pipeline.state = PipelineState.PROCESSING

    pipeline.toggle_recording()
    pipeline.toggle_recording()

    assert len(tracker.named("hotkey_while_busy")) == 2
