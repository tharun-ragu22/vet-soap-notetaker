import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from vet_soap_notetaker.analytics import NullAnalytics
from vet_soap_notetaker.api_client import (
    ApiClientError,
    BackendUnreachableError,
    ExamNotFoundError,
    NotePendingError,
)
from vet_soap_notetaker.paths import get_appdata_base_dir
from vet_soap_notetaker.pipeline import format_soap_text

logger = logging.getLogger("vet_soap_notetaker.offline_queue")


def get_queue_dir() -> Path:
    return get_appdata_base_dir() / "queue"


# A pending note is retried at most this many times when the backend answers
# with an error (the provider keeps failing), then given up on -- the exam stays
# pending in History for a manual Regenerate. An unreachable backend doesn't
# count: like queued audio, that keeps retrying until it's back.
MAX_NOTE_ATTEMPTS = 10

# Queue entries are named queued_<timestamp>, so they sort in recording order.
_STEM_FORMAT = "%Y%m%d_%H%M%S_%f"

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
      cheap ``complete_note`` -- never by re-uploading the audio. Carries an
      ``attempts`` count toward ``MAX_NOTE_ATTEMPTS``.

    Queuing a note completion wakes the polling thread for an immediate pass,
    so a brief provider hiccup resolves in seconds rather than a minute.
    """

    def __init__(
        self,
        api_client,
        on_note_ready,
        queue_dir=None,
        poll_interval_seconds=60,
        on_gave_up=None,
        analytics=None,
        clock=datetime.now,
    ):
        self.api_client = api_client
        self.analytics = analytics or NullAnalytics()
        self._clock = clock
        self.on_note_ready = on_note_ready
        # Called with the exam id when a pending note hits MAX_NOTE_ATTEMPTS.
        self.on_gave_up = on_gave_up or (lambda exam_id: None)
        self.queue_dir = Path(queue_dir) if queue_dir else get_queue_dir()
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        # Set to cut the current poll wait short: a new note entry, or stop().
        self._wake_event = threading.Event()
        self._thread = None

    @staticmethod
    def _new_stem():
        return f"queued_{datetime.now().strftime(_STEM_FORMAT)}"

    def _report_note_ready(self, path, soap_note, queued_as):
        # How long the vet waited for this note, measured from when it was
        # queued (the stem's timestamp) -- for analytics.
        try:
            queued_at = datetime.strptime(path.stem, f"queued_{_STEM_FORMAT}")
            wait_ms = int((self._clock() - queued_at).total_seconds() * 1000)
        except ValueError:
            wait_ms = None
        self.analytics.capture(
            "note_ready",
            {
                "exam_id": soap_note.exam_id,
                "wait_ms": wait_ms,
                "via_offline_queue": True,
                "queued_as": queued_as,
            },
        )

    def enqueue(self, audio_bytes: bytes) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        path = self.queue_dir / f"{self._new_stem()}.wav"
        path.write_bytes(audio_bytes)
        logger.info("queued recording for retry: %s", path)
        return path

    def enqueue_note_completion(self, exam_id: str) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        path = self.queue_dir / f"{self._new_stem()}.json"
        self._write_note_entry(path, exam_id, attempts=0)
        logger.info("queued note completion for exam %s: %s", exam_id, path)
        # Don't wait out the poll interval -- try it now, in the background.
        self._wake_event.set()
        return path

    @staticmethod
    def _write_note_entry(path, exam_id, attempts):
        # Write-then-rename so the polling thread never reads a half-written entry.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"exam_id": exam_id, "attempts": attempts}))
        tmp.replace(path)

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
            # Written directly rather than via enqueue_note_completion: this pass
            # is already running, so it mustn't wake a second one.
            path.unlink()
            note_path = path.with_suffix(".json")
            self._write_note_entry(note_path, exc.exam_id, attempts=0)
            return self._process_note(note_path)
        except ApiClientError as exc:
            logger.info("backend still unavailable, will retry later: %s", exc)
            return _STOP
        path.unlink()
        logger.info("queued recording %s processed successfully", path)
        self._report_note_ready(path, soap_note, "audio")
        # The backend persisted this exam when generate_soap_note() succeeded,
        # so it's already in the shared history the window reads -- no local save.
        self.on_note_ready(format_soap_text(soap_note))
        return _DONE

    def _process_note(self, path):
        try:
            entry = json.loads(path.read_text())
            exam_id = entry["exam_id"]
            # Entries written before attempt counting have no count yet.
            attempts = int(entry.get("attempts", 0))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("dropping unreadable queue entry %s: %s", path, exc)
            path.unlink(missing_ok=True)
            return _DROPPED
        try:
            soap_note = self.api_client.complete_note(exam_id)
        except ExamNotFoundError:
            logger.warning("exam %s no longer exists; dropping its pending note", exam_id)
            path.unlink()
            return _DROPPED
        except BackendUnreachableError as exc:
            logger.info("backend unreachable; note for exam %s will retry later: %s", exam_id, exc)
            return _STOP
        except ApiClientError as exc:
            attempts += 1
            if attempts >= MAX_NOTE_ATTEMPTS:
                logger.warning(
                    "giving up on the note for exam %s after %d attempts: %s",
                    exam_id, attempts, exc,
                )
                path.unlink()
                self.analytics.capture(
                    "pending_note_gave_up", {"exam_id": exam_id, "attempts": attempts}
                )
                self.on_gave_up(exam_id)
                # Nothing wrong with the connection, so move on to the next entry.
                return _DROPPED
            self._write_note_entry(path, exam_id, attempts)
            logger.info(
                "note for exam %s still pending (attempt %d of %d), will retry later: %s",
                exam_id, attempts, MAX_NOTE_ATTEMPTS, exc,
            )
            return _STOP
        path.unlink()
        logger.info("pending note for exam %s completed", exam_id)
        self._report_note_ready(path, soap_note, "pending_note")
        self.on_note_ready(format_soap_text(soap_note))
        return _DONE

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            self._wake_event.wait(self.poll_interval_seconds)
            self._wake_event.clear()
            if self._stop_event.is_set():
                return
            self.process_once()

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
