import enum
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from vet_soap_notetaker import ui_strings
from vet_soap_notetaker.api_client import ApiClientError, NotePendingError
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
        self.state = PipelineState.IDLE
        self.last_soap_text = None

    def _transition(self, new_state):
        self.state = new_state
        self.on_state_change(new_state)

    def toggle_recording(self):
        if self.state == PipelineState.IDLE:
            logger.info("recording started")
            self.recorder.start()
            self._transition(PipelineState.RECORDING)
        elif self.state == PipelineState.RECORDING:
            logger.info("recording stopped, processing")
            self._stop_and_process()
        elif self.state == PipelineState.PROCESSING:
            logger.info("hotkey pressed while the previous note is still processing")
            self.on_busy()

    def _stop_and_process(self):
        self._transition(PipelineState.PROCESSING)
        self.recorder.stop()

        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "recording.wav"
            self.recorder.save_wav(wav_path)
            audio_bytes = wav_path.read_bytes()

        logger.info("sending %d bytes of audio to backend", len(audio_bytes))
        try:
            soap_note = self.api_client.generate_soap_note(audio_bytes)
        except NotePendingError as exc:
            # The backend transcribed and saved this recording but couldn't write
            # the note. Finish that exam from its saved transcript -- never
            # re-upload, which would transcribe again and leave a duplicate exam.
            # Caught before ApiClientError, which it subclasses.
            soap_note = self._finish_pending_note(exc.exam_id)
            if soap_note is None:
                self._transition(PipelineState.IDLE)
                return
        except ApiClientError as exc:
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

        # No local history save here: the backend already persisted this exam
        # when generate_soap_note() posted the audio, and the History window
        # reads that shared record so it syncs across every device.

        logger.info("attempting to inject SOAP note into AVImark")
        injected = self.injector.inject(soap_text)
        logger.info("AVImark injection %s", "succeeded" if injected else "failed, showing flyout")
        if not injected:
            self.on_flyout_needed(soap_text)

        self._transition(PipelineState.IDLE)
        logger.info("done, back to idle")

    def _finish_pending_note(self, exam_id):
        """One immediate attempt at finishing a note-pending exam; on failure,
        queue the exam id (not the audio) for retry and tell the vet.

        Returns the note, or None if it isn't ready yet. The audio is not
        archived: the transcript is already safe on the backend."""
        try:
            return self.api_client.complete_note(exam_id)
        except ApiClientError as exc:
            logger.warning("note for exam %s still pending: %s", exam_id, exc)
            if self.offline_queue is not None:
                self.offline_queue.enqueue_note_completion(exam_id)
            self.on_error(ui_strings.NOTE_PENDING_MESSAGE)
            return None

    def _save_failed_audio(self, audio_bytes):
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.recordings_dir / f"failed_{timestamp}.wav"
        path.write_bytes(audio_bytes)
        return path
