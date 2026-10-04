import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from vet_soap_notetaker.api_client import ApiClientError, SoapNote
from vet_soap_notetaker.offline_queue import OfflineQueue, get_queue_dir


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
