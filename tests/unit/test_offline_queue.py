import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from vet_soap_notetaker.api_client import (
    ApiClientError,
    BackendUnreachableError,
    ExamNotFoundError,
    NotePendingError,
    SoapNote,
)
from vet_soap_notetaker.offline_queue import MAX_NOTE_ATTEMPTS, OfflineQueue, get_queue_dir


def test_get_queue_dir_appends_queue_subdir_to_appdata_base_dir(mocker):
    mocker.patch(
        "vet_soap_notetaker.offline_queue.get_appdata_base_dir",
        return_value=Path("/tmp/vet_soap_notetaker-base"),
    )

    assert get_queue_dir() == Path("/tmp/vet_soap_notetaker-base/queue")


def test_enqueue_writes_wav_bytes_to_queue_dir(tmp_path):
    queue = OfflineQueue(
        api_client=MagicMock(), on_note_ready=MagicMock(), queue_dir=tmp_path / "queue"
    )

    path = queue.enqueue(b"fake-wav-bytes")

    assert path.exists()
    assert path.read_bytes() == b"fake-wav-bytes"
    assert path.parent == tmp_path / "queue"


def test_process_once_processes_all_queued_files_in_order_and_removes_them(tmp_path):
    queue_dir = tmp_path / "queue"
    api_client = MagicMock()
    api_client.generate_soap_note.side_effect = [
        SoapNote(subjective="s1", objective="o1", assessment="a1", plan="p1"),
        SoapNote(subjective="s2", objective="o2", assessment="a2", plan="p2"),
    ]
    on_note_ready = MagicMock()
    queue = OfflineQueue(api_client=api_client, on_note_ready=on_note_ready, queue_dir=queue_dir)
    first = queue.enqueue(b"audio-1")
    time.sleep(0.01)
    second = queue.enqueue(b"audio-2")

    processed = queue.process_once()

    assert processed == [first, second]
    assert not first.exists()
    assert not second.exists()
    assert on_note_ready.call_count == 2
    assert "SUBJECTIVE: s1" in on_note_ready.call_args_list[0][0][0]
    assert "SUBJECTIVE: s2" in on_note_ready.call_args_list[1][0][0]


def test_process_once_stops_at_first_backend_failure_and_leaves_remaining_files_queued(tmp_path):
    queue_dir = tmp_path / "queue"
    api_client = MagicMock()
    api_client.generate_soap_note.side_effect = ApiClientError("still down")
    on_note_ready = MagicMock()
    queue = OfflineQueue(api_client=api_client, on_note_ready=on_note_ready, queue_dir=queue_dir)
    first = queue.enqueue(b"audio-1")

    processed = queue.process_once()

    assert processed == []
    assert first.exists()
    on_note_ready.assert_not_called()


def test_start_runs_process_once_on_background_thread_until_stopped(tmp_path):
    api_client = MagicMock()
    api_client.generate_soap_note.return_value = SoapNote(
        subjective="s", objective="o", assessment="a", plan="p"
    )
    processed_event = threading.Event()
    on_note_ready = MagicMock(side_effect=lambda text: processed_event.set())
    queue = OfflineQueue(
        api_client=api_client,
        on_note_ready=on_note_ready,
        queue_dir=tmp_path / "queue",
        poll_interval_seconds=0.01,
    )
    queue.enqueue(b"audio-1")

    queue.start()
    try:
        assert processed_event.wait(timeout=2)
    finally:
        queue.stop()

    assert not queue._thread.is_alive()


def _note(tag):
    return SoapNote(subjective=f"s{tag}", objective="o", assessment="a", plan="p")


def test_enqueue_note_completion_writes_an_entry_that_is_not_listed_as_audio(tmp_path):
    queue = OfflineQueue(
        api_client=MagicMock(), on_note_ready=MagicMock(), queue_dir=tmp_path / "queue"
    )

    path = queue.enqueue_note_completion("exam-123")

    assert path.exists()
    assert path.parent == tmp_path / "queue"
    assert queue.queued_files() == []


def test_process_once_finishes_a_queued_note_and_removes_the_entry(tmp_path):
    api_client = MagicMock()
    api_client.complete_note.return_value = _note("1")
    on_note_ready = MagicMock()
    queue = OfflineQueue(
        api_client=api_client, on_note_ready=on_note_ready, queue_dir=tmp_path / "queue"
    )
    entry = queue.enqueue_note_completion("exam-123")

    processed = queue.process_once()

    api_client.complete_note.assert_called_once_with("exam-123")
    api_client.generate_soap_note.assert_not_called()
    assert processed == [entry]
    assert not entry.exists()
    on_note_ready.assert_called_once()
    assert "SUBJECTIVE: s1" in on_note_ready.call_args[0][0]


def test_process_once_drops_a_queued_note_whose_exam_was_deleted(tmp_path):
    api_client = MagicMock()
    api_client.complete_note.side_effect = ExamNotFoundError("exam not found")
    on_note_ready = MagicMock()
    queue = OfflineQueue(
        api_client=api_client, on_note_ready=on_note_ready, queue_dir=tmp_path / "queue"
    )
    entry = queue.enqueue_note_completion("exam-gone")

    queue.process_once()

    assert not entry.exists()
    on_note_ready.assert_not_called()


def test_process_once_keeps_a_queued_note_and_stops_when_the_backend_still_fails(tmp_path):
    api_client = MagicMock()
    api_client.complete_note.side_effect = ApiClientError("still down")
    queue = OfflineQueue(
        api_client=api_client, on_note_ready=MagicMock(), queue_dir=tmp_path / "queue"
    )
    first = queue.enqueue_note_completion("exam-1")
    time.sleep(0.01)
    second = queue.enqueue_note_completion("exam-2")

    processed = queue.process_once()

    assert processed == []
    assert first.exists() and second.exists()
    api_client.complete_note.assert_called_once_with("exam-1")


def test_queued_audio_that_gets_a_202_becomes_a_note_entry_and_is_finished(tmp_path):
    # The retried upload got transcribed but note generation failed again:
    # drop the audio (the transcript is saved) and finish the note instead.
    api_client = MagicMock()
    api_client.generate_soap_note.side_effect = NotePendingError("exam-123")
    api_client.complete_note.return_value = _note("1")
    on_note_ready = MagicMock()
    queue_dir = tmp_path / "queue"
    queue = OfflineQueue(api_client=api_client, on_note_ready=on_note_ready, queue_dir=queue_dir)
    audio = queue.enqueue(b"audio-1")

    queue.process_once()

    assert not audio.exists()
    api_client.complete_note.assert_called_once_with("exam-123")
    on_note_ready.assert_called_once()
    assert list(queue_dir.iterdir()) == []


def test_queued_audio_that_gets_a_202_keeps_a_note_entry_when_finishing_fails(tmp_path):
    api_client = MagicMock()
    api_client.generate_soap_note.side_effect = NotePendingError("exam-123")
    api_client.complete_note.side_effect = ApiClientError("still failing")
    queue_dir = tmp_path / "queue"
    queue = OfflineQueue(api_client=api_client, on_note_ready=MagicMock(), queue_dir=queue_dir)
    audio = queue.enqueue(b"audio-1")

    queue.process_once()

    assert not audio.exists()
    assert queue.queued_files() == []
    remaining = list(queue_dir.iterdir())
    assert len(remaining) == 1

    # Next poll: only the cheap note completion is retried, never the upload.
    api_client.complete_note.side_effect = None
    api_client.complete_note.return_value = _note("1")
    queue.process_once()
    assert api_client.generate_soap_note.call_count == 1
    assert list(queue_dir.iterdir()) == []


def test_process_once_handles_audio_and_note_entries_in_recording_order(tmp_path):
    calls = []
    api_client = MagicMock()
    api_client.generate_soap_note.side_effect = lambda audio: calls.append(("audio", audio)) or _note("a")
    api_client.complete_note.side_effect = lambda exam_id: calls.append(("note", exam_id)) or _note("n")
    queue = OfflineQueue(
        api_client=api_client, on_note_ready=MagicMock(), queue_dir=tmp_path / "queue"
    )
    queue.enqueue_note_completion("exam-1")
    time.sleep(0.01)
    queue.enqueue(b"audio-2")
    time.sleep(0.01)
    queue.enqueue_note_completion("exam-3")

    queue.process_once()

    assert calls == [("note", "exam-1"), ("audio", b"audio-2"), ("note", "exam-3")]


def test_queuing_a_note_completion_triggers_a_pass_right_away(tmp_path):
    # A brief provider hiccup should resolve in seconds, not wait out the 60s
    # poll interval.
    api_client = MagicMock()
    api_client.complete_note.return_value = _note("1")
    ready = threading.Event()
    queue = OfflineQueue(
        api_client=api_client,
        on_note_ready=lambda text: ready.set(),
        queue_dir=tmp_path / "queue",
        poll_interval_seconds=60,
    )
    queue.start()
    try:
        queue.enqueue_note_completion("exam-123")
        assert ready.wait(timeout=2)
    finally:
        queue.stop()

    assert not queue._thread.is_alive()


def test_stop_ends_the_thread_promptly_even_with_a_long_poll_interval(tmp_path):
    queue = OfflineQueue(
        api_client=MagicMock(),
        on_note_ready=MagicMock(),
        queue_dir=tmp_path / "queue",
        poll_interval_seconds=60,
    )
    queue.start()
    started = time.monotonic()

    queue.stop()

    assert not queue._thread.is_alive()
    assert time.monotonic() - started < 2


def test_a_queued_note_gives_up_after_the_retry_limit_and_reports_it(tmp_path):
    # The provider keeps answering with an error: stop after the limit rather
    # than retry forever. The exam stays pending in History for a manual retry.
    api_client = MagicMock()
    api_client.complete_note.side_effect = ApiClientError("backend returned 502")
    on_gave_up = MagicMock()
    queue = OfflineQueue(
        api_client=api_client,
        on_note_ready=MagicMock(),
        queue_dir=tmp_path / "queue",
        on_gave_up=on_gave_up,
    )
    entry = queue.enqueue_note_completion("exam-123")

    for _ in range(MAX_NOTE_ATTEMPTS - 1):
        queue.process_once()
    assert entry.exists()
    on_gave_up.assert_not_called()

    queue.process_once()

    assert not entry.exists()
    assert api_client.complete_note.call_count == MAX_NOTE_ATTEMPTS
    on_gave_up.assert_called_once_with("exam-123")


def test_an_unreachable_backend_does_not_use_up_a_queued_notes_retries(tmp_path):
    # The backend being down (restart, Wi-Fi blip) isn't the note's fault --
    # keep retrying indefinitely, like queued audio.
    api_client = MagicMock()
    api_client.complete_note.side_effect = BackendUnreachableError("connection refused")
    on_gave_up = MagicMock()
    queue = OfflineQueue(
        api_client=api_client,
        on_note_ready=MagicMock(),
        queue_dir=tmp_path / "queue",
        on_gave_up=on_gave_up,
    )
    entry = queue.enqueue_note_completion("exam-123")

    for _ in range(MAX_NOTE_ATTEMPTS + 5):
        queue.process_once()

    assert entry.exists()
    on_gave_up.assert_not_called()


def test_a_note_entry_written_before_attempt_counting_still_loads(tmp_path):
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    (queue_dir / "queued_20261013_120000_000000.json").write_text('{"exam_id": "exam-old"}')
    api_client = MagicMock()
    api_client.complete_note.return_value = _note("1")
    on_note_ready = MagicMock()
    queue = OfflineQueue(api_client=api_client, on_note_ready=on_note_ready, queue_dir=queue_dir)

    queue.process_once()

    api_client.complete_note.assert_called_once_with("exam-old")
    on_note_ready.assert_called_once()


# --- Analytics -----------------------------------------------------------------

from datetime import datetime  # noqa: E402

from tests.fakes import RecordingAnalytics  # noqa: E402


def _tracked_queue(tmp_path, api_client, now):
    tracker = RecordingAnalytics()
    queue = OfflineQueue(
        api_client=api_client,
        on_note_ready=MagicMock(),
        queue_dir=tmp_path / "queue",
        analytics=tracker,
        clock=lambda: now,
    )
    return queue, tracker


def test_a_recovered_recording_reports_how_long_it_waited_in_the_queue(tmp_path):
    api_client = MagicMock()
    api_client.generate_soap_note.return_value = SoapNote("s", "o", "a", "p", exam_id="exam-1")
    queue, tracker = _tracked_queue(tmp_path, api_client, datetime(2026, 10, 13, 9, 5, 0))
    (tmp_path / "queue").mkdir()
    (tmp_path / "queue" / "queued_20261013_090000_000000.wav").write_bytes(b"wav")

    queue.process_once()

    assert tracker.only("note_ready")["properties"] == {
        "exam_id": "exam-1",
        "wait_ms": 300000,
        "via_offline_queue": True,
        "queued_as": "audio",
    }


def test_a_finished_pending_note_reports_its_wait(tmp_path):
    api_client = MagicMock()
    api_client.complete_note.return_value = SoapNote("s", "o", "a", "p", exam_id="exam-2")
    queue, tracker = _tracked_queue(tmp_path, api_client, datetime(2026, 10, 13, 9, 0, 30))
    (tmp_path / "queue").mkdir()
    (tmp_path / "queue" / "queued_20261013_090000_000000.json").write_text(
        '{"exam_id": "exam-2", "attempts": 0}'
    )

    queue.process_once()

    props = tracker.only("note_ready")["properties"]
    assert props["wait_ms"] == 30000
    assert props["queued_as"] == "pending_note"
    assert props["exam_id"] == "exam-2"


def test_giving_up_on_a_pending_note_is_reported(tmp_path):
    api_client = MagicMock()
    api_client.complete_note.side_effect = ApiClientError("backend returned 502")
    queue, tracker = _tracked_queue(tmp_path, api_client, datetime(2026, 10, 13, 9, 0, 0))
    queue.enqueue_note_completion("exam-3")

    for _ in range(MAX_NOTE_ATTEMPTS):
        queue.process_once()

    assert tracker.only("pending_note_gave_up")["properties"] == {
        "exam_id": "exam-3",
        "attempts": MAX_NOTE_ATTEMPTS,
    }
