import enum
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.analytics import NullAnalytics, injection_properties
from vet_soap_notetaker.api_client import (
    ApiClientError,
    BackendUnreachableError,
    NoSpeechError,
    NotePendingError,
)
from vet_soap_notetaker.paths import get_appdata_base_dir

logger = logging.getLogger("vet_soap_notetaker.pipeline")


class PipelineState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


def format_soap_text(soap_note) -> str:
    return (
        f"SUBJECTIVE: {soap_note.subjective}\n"
        f"OBJECTIVE: {soap_note.objective}\n"
        f"ASSESSMENT: {soap_note.assessment}\n"
        f"PLAN: {soap_note.plan}"
    )


class Pipeline:
    def __init__(
        self,
        recorder,
        api_client,
        injector,
        on_flyout_needed,
        on_error=None,
        recordings_dir=None,
        offline_queue=None,
        on_state_change=None,
        on_busy=None,
        analytics=None,
        clock=time.monotonic,
    ):
        self.recorder = recorder
        self.api_client = api_client
        self.injector = injector
        self.on_flyout_needed = on_flyout_needed
        self.on_error = on_error or (lambda message: None)
        # Share one data root with history/ and queue/ (%APPDATA%\Vet Soap Notetaker on
        # Windows, ~/.vetscribe elsewhere) so all Vet Soap Notetaker data lives together.
        self.recordings_dir = Path(recordings_dir) if recordings_dir else (
            get_appdata_base_dir() / "recordings"
        )
        self.offline_queue = offline_queue
        self.on_state_change = on_state_change or (lambda state: None)
        # Called when the hotkey is pressed mid-PROCESSING, which can't start a
        # new recording -- so the vet is told why instead of getting a silent
        # no-op. Purely a notice: the state machine is unchanged.
        self.on_busy = on_busy or (lambda: None)
        # Metadata-only usage events: timings, outcomes, how the note landed.
        self.analytics = analytics or NullAnalytics()
        self._clock = clock
        self._recording_started_at = None
        self.state = PipelineState.IDLE
        self.last_soap_text = None

    def _transition(self, new_state):
        self.state = new_state
        self.on_state_change(new_state)

    def toggle_recording(self):
        if self.state == PipelineState.IDLE:
            logger.info("recording started")
            self.recorder.start()
            self._recording_started_at = self._clock()
            self.analytics.capture("recording_started")
            self._transition(PipelineState.RECORDING)
        elif self.state == PipelineState.RECORDING:
            logger.info("recording stopped, processing")
            self._stop_and_process()
        elif self.state == PipelineState.PROCESSING:
            logger.info("hotkey pressed while the previous note is still processing")
            self.analytics.capture("hotkey_while_busy")
            self.on_busy()

    def _stop_and_process(self):
        self._transition(PipelineState.PROCESSING)
        self.recorder.stop()
        stopped_at = self._clock()
        started_at = self._recording_started_at
        recording_ms = int((stopped_at - started_at) * 1000) if started_at is not None else None
        self.analytics.capture("recording_stopped", {"recording_ms": recording_ms})

        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "recording.wav"
            self.recorder.save_wav(wav_path)
            audio_bytes = wav_path.read_bytes()

        logger.info("sending %d bytes of audio to backend", len(audio_bytes))
        try:
            soap_note = self.api_client.generate_soap_note(
                audio_bytes, audio_duration_ms=recording_ms
            )
        except NotePendingError as exc:
            self._report_failure(exc, stopped_at, recording_ms)
            # The backend transcribed and saved this recording but couldn't write
            # the note. The offline queue finishes that exam from its saved
            # transcript, in the background (it runs a pass right away) -- never
            # re-upload, which would transcribe again and leave a duplicate exam.
            # Not retried inline: when the provider is down that would add a
            # whole provider timeout to the vet's wait. The audio isn't archived;
            # the transcript is safe on the backend. Caught before
            # ApiClientError, which it subclasses.
            logger.warning("note for exam %s pending; queued for completion", exc.exam_id)
            if self.offline_queue is not None:
                self.offline_queue.enqueue_note_completion(exc.exam_id)
            self.on_error(ui_strings.NOTE_PENDING_MESSAGE)
            self._transition(PipelineState.IDLE)
            return
        except NoSpeechError as exc:
            # 422: nothing was said. Archive the WAV (no data loss) but don't
            # queue it -- re-sending the same audio would fail the same way and
            # pay for transcription every pass. Caught before ApiClientError,
            # which it subclasses.
            self._report_failure(exc, stopped_at, recording_ms)
            saved_path = self._save_failed_audio(audio_bytes)
            logger.warning("backend heard no speech (audio saved to %s)", saved_path)
            self.on_error(ui_strings.NO_SPEECH_MESSAGE.format(path=saved_path))
            self._transition(PipelineState.IDLE)
            return
        except ApiClientError as exc:
            self._report_failure(exc, stopped_at, recording_ms)
            saved_path = self._save_failed_audio(audio_bytes)
            logger.error("SOAP generation failed: %s (audio saved to %s)", exc, saved_path)
            if self.offline_queue is not None:
                self.offline_queue.enqueue(audio_bytes)
            self.on_error(
                f"SOAP Generation Failed: {exc}. Raw audio saved locally to {saved_path}."
            )
            self._transition(PipelineState.IDLE)
            return

        soap_text = format_soap_text(soap_note)
        self.last_soap_text = soap_text
        logger.info("SOAP note generated successfully")
        self.analytics.capture(
            "note_ready",
            {
                "exam_id": soap_note.exam_id,
                "wait_ms": int((self._clock() - stopped_at) * 1000),
                "recording_ms": recording_ms,
                "via_offline_queue": False,
            },
        )

        # No local history save here: the backend already persisted this exam
        # when generate_soap_note() posted the audio, and the History window
        # reads that shared record so it syncs across every device.

        logger.info("attempting to inject SOAP note into AVImark")
        injected = self.injector.inject(soap_text)
        logger.info("AVImark injection %s", "succeeded" if injected else "failed, showing flyout")
        self.analytics.capture(
            "injection_completed",
            injection_properties(
                "hotkey",
                self.injector.last_result,
                injected,
                fallback_flyout_shown=not injected,
                exam_id=soap_note.exam_id,
            ),
        )
        if not injected:
            self.on_flyout_needed(soap_text)

        self._transition(PipelineState.IDLE)
        logger.info("done, back to idle")

    def _report_failure(self, exc, stopped_at, recording_ms):
        # The error's type only, never its message (it carries backend bodies).
        if isinstance(exc, NotePendingError):
            outcome = "note_pending"
        elif isinstance(exc, NoSpeechError):
            outcome = "no_speech"
        elif isinstance(exc, BackendUnreachableError):
            outcome = "backend_unreachable"
        else:
            outcome = "backend_error"
        self.analytics.capture(
            "note_failed",
            {
                "outcome": outcome,
                "error_type": type(exc).__name__,
                "exam_id": getattr(exc, "exam_id", None),
                "wait_ms": int((self._clock() - stopped_at) * 1000),
                "recording_ms": recording_ms,
                "queued": self.offline_queue is not None and not isinstance(exc, NoSpeechError),
            },
        )

    def _save_failed_audio(self, audio_bytes):
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.recordings_dir / f"failed_{timestamp}.wav"
        path.write_bytes(audio_bytes)
        return path
