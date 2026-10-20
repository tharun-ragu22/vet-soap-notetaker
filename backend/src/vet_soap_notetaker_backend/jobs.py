"""Background processing for uploads sent with ``Prefer: respond-async``.

The upload handler only saves the audio and a ``processing`` appointment, then
replies 202 -- so the phone isn't left holding a connection open through
transcription and note generation (losing it made the phone re-upload, which
duplicated the appointment and paid for transcription twice). This worker does
the rest, one appointment at a time, and publishes the outcome to the EventHub
for the phone's ``/api/events`` stream.

Everything it needs survives a restart: the appointment (with its stage) is in
the store and the audio is a file in ``audio_dir``, so ``resume()`` re-queues
whatever was still processing.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from vet_soap_notetaker_backend.events import EventHub
from vet_soap_notetaker_backend.llm.transcription import NoSpeechError
from vet_soap_notetaker_backend.schemas import SoapResult
from vet_soap_notetaker_backend.store import Appointment, ExamStore

logger = logging.getLogger("vet_soap_notetaker_backend.jobs")

_EXTENSIONS = {"audio/mp4": ".m4a", "audio/wav": ".wav"}

# (appointment_id, outcome, metadata) -- metadata is timings, counts and error
# type names only, for analytics and the log line.
OutcomeCallback = Callable[[str, str, dict], None]


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class AppointmentWorker:
    def __init__(
        self,
        *,
        store: ExamStore,
        hub: EventHub,
        audio_dir: Path,
        transcribe: Callable[[bytes, str], Awaitable[str]],
        generate: Callable[[str], Awaitable[SoapResult]],
        provider_errors: tuple[type[Exception], ...],
        on_outcome: OutcomeCallback | None = None,
    ):
        self._store = store
        self._hub = hub
        self._audio_dir = Path(audio_dir)
        self._transcribe = transcribe
        self._generate = generate
        self._provider_errors = provider_errors
        self._on_outcome = on_outcome
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    # --- audio files ---------------------------------------------------------

    @property
    def audio_dir(self) -> Path:
        return self._audio_dir

    def audio_path(self, appointment: Appointment) -> Path:
        ext = _EXTENSIONS.get(appointment.audio_mime or "", ".audio")
        return self._audio_dir / f"{appointment.id}{ext}"

    async def save_audio(self, appointment: Appointment, audio: bytes) -> None:
        """Write the upload durably (tmp + atomic replace) before it's queued."""
        await run_in_threadpool(self._write_audio, self.audio_path(appointment), audio)

    def _write_audio(self, path: Path, audio: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)

    def _delete_audio(self, appointment: Appointment) -> None:
        self.audio_path(appointment).unlink(missing_ok=True)

    # --- queue ---------------------------------------------------------------

    def submit(self, appointment_id: str) -> None:
        self._queue.put_nowait(appointment_id)

    def resume(self) -> None:
        """At startup: re-queue everything still processing, and delete audio
        files no appointment needs any more (a crash between saving the file and
        the appointment, or between finishing and deleting)."""
        processing = self._store.list_processing()
        for appointment in processing:
            self.submit(appointment.id)
        if not self._audio_dir.exists():
            return
        keep = {self.audio_path(a).name for a in self._store.list_appointments()
                if a.stage in ("processing", "failed")}
        for path in self._audio_dir.iterdir():
            if path.name not in keep:
                path.unlink(missing_ok=True)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def drain(self) -> None:
        """Wait until every submitted appointment has been processed (tests)."""
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            appointment_id = await self._queue.get()
            try:
                await self._process(appointment_id)
            except Exception:  # noqa: BLE001 - one bad job must never stop the worker
                logger.exception("processing appointment %s crashed", appointment_id)
            finally:
                self._queue.task_done()

    # --- one appointment -----------------------------------------------------

    async def _process(self, appointment_id: str) -> None:
        appointment = self._store.get_appointment(appointment_id)
        if appointment is None:
            # Deleted before its turn came: its audio isn't wanted either.
            for path in self._audio_dir.glob(f"{appointment_id}.*"):
                path.unlink(missing_ok=True)
            return
        if appointment.stage != "processing":
            return
        started = time.perf_counter()
        info: dict = {}
        try:
            audio = await run_in_threadpool(self.audio_path(appointment).read_bytes)
            transcript = await self._transcribe(audio, appointment.audio_mime or "audio/wav")
        except NoSpeechError:
            info["transcribe_ms"] = _elapsed_ms(started)
            self._delete_audio(appointment)
            return self._finish(self._store.mark_failed(appointment_id, "no_speech"), info)
        except Exception as exc:  # noqa: BLE001 - provider error, lost file, or a bug
            # The audio is kept: Retry (POST .../retry) runs it again.
            info.update(transcribe_ms=_elapsed_ms(started), error=type(exc).__name__)
            if not isinstance(exc, self._provider_errors):
                logger.warning("transcription crashed: %s", type(exc).__name__)
            return self._finish(self._store.mark_failed(appointment_id, "failed"), info)
        info["transcribe_ms"] = _elapsed_ms(started)

        note_started = time.perf_counter()
        try:
            result = await self._generate(transcript)
        except Exception as exc:  # noqa: BLE001 - as above
            info.update(note_gen_ms=_elapsed_ms(note_started), error=type(exc).__name__)
            self._delete_audio(appointment)
            return self._finish(self._store.mark_note_pending(appointment_id, transcript), info)
        info["note_gen_ms"] = _elapsed_ms(note_started)
        self._delete_audio(appointment)
        finished = self._store.finish_processing(appointment_id, result.transcript, result.notes)
        if finished is not None:
            info["patient_count"] = len(finished.exams)
        self._finish(finished, info)

    def _finish(self, appointment: Appointment | None, info: dict) -> None:
        # None: the vet deleted it while it was processing -- nothing to announce.
        if appointment is None:
            return
        if self._on_outcome is not None:
            self._on_outcome(appointment.id, appointment.status, info)
        self._hub.publish(
            {
                "id": appointment.id,
                "status": appointment.status,
                "patient_names": [e.patient_name for e in appointment.exams if e.patient_name]
                if appointment.stage is None and not appointment.note_pending
                else [],
            }
        )
