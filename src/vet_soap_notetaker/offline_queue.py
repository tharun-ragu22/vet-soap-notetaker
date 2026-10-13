import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from vet_soap_notetaker.api_client import ApiClientError, ExamNotFoundError, NotePendingError
from vet_soap_notetaker.paths import get_appdata_base_dir
from vet_soap_notetaker.pipeline import format_soap_text

logger = logging.getLogger("vet_soap_notetaker.offline_queue")


def get_queue_dir() -> Path:
    return get_appdata_base_dir() / "queue"


# Outcome of processing one queue entry.
_DONE = "done"  # note ready, entry removed
_DROPPED = "dropped"  # nothing left to do (exam deleted / unreadable), entry removed
_STOP = "stop"  # backend still failing; keep the entry, end this pass


class OfflineQueue:
    """Retries backend work that failed, on a background polling thread.

    Two kinds of entry, named ``queued_<timestamp>`` so a name sort keeps them in
    recording order:

    * ``.wav`` -- a recording whose upload failed; retried with
      ``generate_soap_note``.
    * ``.json`` -- ``{"exam_id": ...}`` for an exam the backend already
      transcribed and saved whose note is pending (HTTP 202); retried with the
      cheap ``complete_note`` -- never by re-uploading the audio.
    """

    def __init__(
        self,
        api_client,
        on_note_ready,
        queue_dir=None,
        poll_interval_seconds=60,
    ):
        self.api_client = api_client
        self.on_note_ready = on_note_ready
        self.queue_dir = Path(queue_dir) if queue_dir else get_queue_dir()
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread = None

    @staticmethod
    def _new_stem():
        return f"queued_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    def enqueue(self, audio_bytes: bytes) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        path = self.queue_dir / f"{self._new_stem()}.wav"
        path.write_bytes(audio_bytes)
        logger.info("queued recording for retry: %s", path)
        return path

    def enqueue_note_completion(self, exam_id: str, stem=None) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        path = self.queue_dir / f"{stem or self._new_stem()}.json"
        # Write-then-rename so the polling thread never reads a half-written entry.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"exam_id": exam_id}))
        tmp.replace(path)
        logger.info("queued note completion for exam %s: %s", exam_id, path)
        return path

    def queued_files(self):
        if not self.queue_dir.exists():
            return []
        return sorted(self.queue_dir.glob("queued_*.wav"))

    def _entries(self):
        if not self.queue_dir.exists():
            return []
        return sorted(
            p for p in self.queue_dir.glob("queued_*") if p.suffix in (".wav", ".json")
        )

    def process_once(self):
        pending = self._entries()
        if not pending:
            logger.debug("retry poll: nothing queued")
            return []
        logger.info("retry poll: %d queued item(s) pending", len(pending))

        processed = []
        for path in pending:
            if path.suffix == ".wav":
                outcome = self._process_audio(path)
            else:
                outcome = self._process_note(path)
            if outcome == _STOP:
                break
            if outcome == _DONE:
                processed.append(path)
        return processed

    def _process_audio(self, path):
        audio_bytes = path.read_bytes()
        try:
            soap_note = self.api_client.generate_soap_note(audio_bytes)
        except NotePendingError as exc:
            # Transcribed and saved this time, but the note failed: the audio is
            # no longer needed. Swap it for a note entry (same stem, so it keeps
            # its place in line) and try finishing it straight away.
            path.unlink()
            note_path = self.enqueue_note_completion(exc.exam_id, stem=path.stem)
            return self._process_note(note_path)
        except ApiClientError as exc:
            logger.info("backend still unavailable, will retry later: %s", exc)
            return _STOP
        path.unlink()
        logger.info("queued recording %s processed successfully", path)
        # The backend persisted this exam when generate_soap_note() succeeded,
        # so it's already in the shared history the window reads -- no local save.
        self.on_note_ready(format_soap_text(soap_note))
        return _DONE

    def _process_note(self, path):
        try:
            exam_id = json.loads(path.read_text())["exam_id"]
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("dropping unreadable queue entry %s: %s", path, exc)
            path.unlink(missing_ok=True)
            return _DROPPED
        try:
            soap_note = self.api_client.complete_note(exam_id)
        except ExamNotFoundError:
            logger.warning("exam %s no longer exists; dropping its pending note", exam_id)
            path.unlink()
            return _DROPPED
        except ApiClientError as exc:
            logger.info("note for exam %s still pending, will retry later: %s", exam_id, exc)
            return _STOP
        path.unlink()
        logger.info("pending note for exam %s completed", exam_id)
        self.on_note_ready(format_soap_text(soap_note))
        return _DONE

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(self.poll_interval_seconds):
            self.process_once()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
