import asyncio
import hashlib
import json
import logging
import socket
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.sse import KEEPALIVE_COMMENT, EventSourceResponse, format_sse_event
from starlette.concurrency import run_in_threadpool

from vet_soap_notetaker_backend.analytics import (
    Analytics,
    edit_summary,
    error_properties,
    make_analytics,
)
from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.events import EventHub
from vet_soap_notetaker_backend.jobs import AppointmentWorker
from vet_soap_notetaker_backend.injection_queue import InjectionQueue
from vet_soap_notetaker_backend.llm.note_generation import get_note_generator
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError
from vet_soap_notetaker_backend.llm.pipeline import SoapPipeline
from vet_soap_notetaker_backend.schemas import SoapResult
from vet_soap_notetaker_backend.store import Appointment, Exam, ExamEdit, ExamStore
from vet_soap_notetaker_backend.llm.transcription import NoSpeechError, get_transcriber
from vet_soap_notetaker_backend.llm.transcription.audio_format import DEFAULT_MIME, transcription_mime
from vet_soap_notetaker_backend.llm.transcription.silence import is_silent_wav
from vet_soap_notetaker_backend.llm.transcription.gemini_transcriber import TranscriptionError

logger = logging.getLogger("vet_soap_notetaker_backend.app")

_SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")
_NOTE_FIELDS = (*_SOAP_FIELDS, "transcript")
# Client-supplied analytics headers longer than this are ignored rather than
# forwarded to PostHog.
_MAX_ANALYTICS_HEADER_LEN = 200
# The phone sends its queue entry's UUID; anything longer isn't one.
_MAX_IDEMPOTENCY_KEY_LEN = 128


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _parse_exam_edits(body: dict) -> list[ExamEdit] | str:
    """The animals in a PUT /api/appointments/{id} body, or what's wrong with it."""
    if not isinstance(body.get("transcript"), str):
        return "missing or invalid field: transcript"
    exams = body.get("exams")
    if not isinstance(exams, list) or not exams:
        return "exams must be a non-empty list; delete the appointment instead"
    edits = []
    for entry in exams:
        if not isinstance(entry, dict):
            return "each exam must be an object"
        missing = [f for f in _SOAP_FIELDS if not isinstance(entry.get(f), str)]
        if missing:
            return f"missing or invalid fields: {', '.join(missing)}"
        for optional in ("patient_name", "id"):
            if entry.get(optional) is not None and not isinstance(entry[optional], str):
                return f"{optional} must be a string"
        edits.append(
            ExamEdit(
                **{f: entry[f] for f in _SOAP_FIELDS},
                patient_name=entry.get("patient_name"),
                id=entry.get("id"),
            )
        )
    return edits


def create_app(
    config: BackendConfig | None = None,
    pipeline: SoapPipeline | None = None,
    store: ExamStore | None = None,
    injection_queue: InjectionQueue | None = None,
    analytics: Analytics | None = None,
    audio_dir: Path | str | None = None,
    events_keepalive_seconds: float = 15.0,
) -> FastAPI:
    config = config or BackendConfig.from_env()
    pipeline = pipeline or SoapPipeline(
        transcriber=get_transcriber(config),
        note_generator=get_note_generator(config),
    )
    store = store if store is not None else ExamStore()
    injection_queue = injection_queue if injection_queue is not None else InjectionQueue()
    analytics = analytics if analytics is not None else make_analytics(config)
    # Where async uploads wait to be processed (main.py puts it next to the
    # exams file, so it survives restarts); tests get a throwaway directory.
    audio_dir = Path(audio_dir) if audio_dir is not None else Path(
        tempfile.mkdtemp(prefix="vsn-incoming-")
    )
    events = EventHub()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Pick up uploads a restart interrupted, then process new ones.
        worker.resume()
        worker.start()
        yield
        await worker.stop()
        # Flush whatever the client has batched before the process exits.
        analytics.shutdown()

    app = FastAPI(lifespan=lifespan)

    # --- Analytics -----------------------------------------------------------
    # Events are metadata only (see analytics.py). They're attributed to the
    # client's own PostHog id (X-POSTHOG-DISTINCT-ID) so the backend's events
    # land on the same person as the phone's/desktop's, falling back to the
    # configured id, then to this machine.
    default_user_id = config.analytics_user_id or f"backend-{socket.gethostname()}"
    # In memory only (reset on restart): exams regenerated since their last
    # save, and exams the vet has edited -- for note_saved/injection_requested.
    regenerated_exams: set[str] = set()
    regenerated_appointments: set[str] = set()
    edited_exams: set[str] = set()

    def _header(request: Request, name: str) -> str | None:
        value = request.headers.get(name, "").strip()
        return value if 0 < len(value) <= _MAX_ANALYTICS_HEADER_LEN else None

    def _track(request: Request, event: str, **properties) -> None:
        props = {"source_app": _header(request, "x-vsn-client") or "unknown", **properties}
        session_id = _header(request, "x-posthog-session-id")
        if session_id:
            props["$session_id"] = session_id
        distinct_id = _header(request, "x-posthog-distinct-id") or default_user_id
        analytics.capture(event, distinct_id, props)

    def _audio_duration_ms(request: Request) -> int | None:
        # Sent by the client, which knows the recording length; the backend
        # can't read it from an m4a (mobile) body.
        try:
            return int(_header(request, "x-audio-duration-ms") or "")
        except ValueError:
            return None

    def _unauthorized(request: Request) -> JSONResponse | None:
        if not config.backend_api_key:
            return None
        expected = f"Bearer {config.backend_api_key}"
        if request.headers.get("authorization") != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    def _provider_error_response(exc: Exception) -> JSONResponse:
        # Map every provider-level failure to a clean 502 rather than a raw 500
        # traceback. New provider failure modes belong in _PROVIDER_ERRORS.
        # The body is a fixed summary, never str(exc): httpx error text carries
        # the full provider URL (an API key, for a provider that puts one in the
        # query string), and parsing errors can quote model output -- and the
        # clients show this body on screen and write it to their logs. The full
        # error stays in this backend's own log.
        logger.warning("provider call failed: %s: %s", type(exc).__name__, exc)
        if isinstance(exc, httpx.HTTPStatusError):
            message = f"upstream provider returned {exc.response.status_code}"
        elif isinstance(exc, httpx.RequestError):
            message = f"upstream provider unreachable ({type(exc).__name__})"
        elif isinstance(exc, TranscriptionError):
            message = f"transcription failed ({type(exc).__name__})"
        else:
            message = f"note generation failed ({type(exc).__name__})"
        return JSONResponse({"error": message}, status_code=502)

    # Provider calls block (sync httpx, retry backoff sleeps, Files API polling)
    # and a long recording can take minutes. Run them on Starlette's thread pool
    # so the event loop keeps serving every other request meanwhile -- called
    # directly, one transcription stalls the desktop's injection poll, History
    # and saves until it returns. Exceptions re-raise here, so the error
    # mapping below is unchanged.
    async def _transcribe(audio_bytes: bytes, mime_type: str) -> str:
        # A silent WAV never reaches the provider: it costs money and, given
        # silence, a model can invent a whole conversation. Reading a long WAV
        # takes a second or two, so it runs off the event loop too.
        if mime_type == DEFAULT_MIME and await run_in_threadpool(is_silent_wav, audio_bytes):
            raise NoSpeechError()
        return await run_in_threadpool(pipeline.transcribe, audio_bytes, mime_type)

    async def _generate(transcript: str):
        return await run_in_threadpool(pipeline.generate_from_transcript, transcript)

    _PROVIDER_ERRORS = (
        httpx.HTTPStatusError,
        httpx.RequestError,
        NoteParsingError,
        TranscriptionError,
    )

    # Analytics attribution for async uploads, captured from the upload request
    # (the worker has no request to read it from). In memory: after a restart a
    # resumed job is attributed to the default id.
    job_clients: dict[str, dict] = {}

    def _job_outcome(appointment_id: str, outcome: str, info: dict) -> None:
        client = job_clients.pop(appointment_id, {})
        distinct_id = client.pop("distinct_id", default_user_id)
        info = dict(info)
        if "error" in info:
            info["error_type"] = info.pop("error")
        props = {
            "source_app": client.pop("source_app", "unknown"),
            "mode": "async",
            "outcome": outcome,
            "appointment_id": appointment_id,
            "transcription_provider": config.transcription_provider,
            "note_provider": config.note_provider,
            **client,
            **info,
        }
        analytics.capture("soap_generated", distinct_id, props)
        logger.info(
            "recording processed: mode=async outcome=%s %s",
            outcome,
            " ".join(f"{k}={v}" for k, v in info.items()),
        )

    worker = AppointmentWorker(
        store=store,
        hub=events,
        audio_dir=audio_dir,
        transcribe=_transcribe,
        generate=_generate,
        provider_errors=_PROVIDER_ERRORS,
        on_outcome=_job_outcome,
    )
    app.state.worker = worker
    app.state.events = events

    def _wants_async(request: Request) -> bool:
        prefer = request.headers.get("prefer", "")
        return "respond-async" in (token.strip().lower() for token in prefer.split(","))

    def _no_transcript_yet(appointment: Appointment) -> JSONResponse | None:
        if appointment.stage is None:
            return None
        return JSONResponse({"error": "recording has no transcript yet"}, status_code=409)

    async def _create_appointment_async(request: Request) -> JSONResponse:
        """Save the upload and reply at once; AppointmentWorker does the rest.
        A repeat with the same Idempotency-Key gets that appointment back --
        whatever state it's in -- so a reply lost in transit never makes a
        duplicate or pays for transcription twice."""
        key = request.headers.get("idempotency-key", "").strip() or None
        if key is not None and len(key) > _MAX_IDEMPOTENCY_KEY_LEN:
            return JSONResponse({"error": "Idempotency-Key is too long"}, status_code=400)
        audio_bytes = await request.body()
        if not audio_bytes:
            return JSONResponse({"error": "empty request body"}, status_code=400)
        sha = await run_in_threadpool(lambda: hashlib.sha256(audio_bytes).hexdigest())
        mime = transcription_mime(request.headers.get("content-type"))

        appointment, created = store.create_processing(key, sha, mime)
        if not created:
            if appointment.audio_sha256 != sha:
                return JSONResponse(
                    {"error": "key already used for a different recording"}, status_code=409
                )
            logger.info("recording upload repeated: status=%s", appointment.status)
            still_going = appointment.status in ("processing", "note_pending")
            return JSONResponse(appointment.to_dict(), status_code=202 if still_going else 200)

        await worker.save_audio(appointment, audio_bytes)
        job_clients[appointment.id] = {
            "distinct_id": _header(request, "x-posthog-distinct-id") or default_user_id,
            "source_app": _header(request, "x-vsn-client") or "unknown",
            "audio_bytes": len(audio_bytes),
            "audio_duration_ms": _audio_duration_ms(request),
            "audio_mime": mime,
        }
        worker.submit(appointment.id)
        return JSONResponse(appointment.to_dict(), status_code=202)

    def _log_recording(outcome: str, started: float, timing: dict, **extra) -> None:
        # One line per recording so a slow step shows in the console without
        # PostHog. Metadata only, like the analytics event.
        fields = {
            "outcome": outcome,
            "transcribe_ms": timing.get("transcribe_ms"),
            **extra,
            "total_ms": _elapsed_ms(started),
            "audio_bytes": timing["audio_bytes"],
            "audio_duration_ms": timing["audio_duration_ms"],
            "audio_mime": timing["audio_mime"],
        }
        logger.info("recording processed: %s", " ".join(f"{k}={v}" for k, v in fields.items()))

    async def _create_appointment(request: Request) -> JSONResponse | tuple[Appointment, int]:
        """Transcribe the uploaded audio and generate a note per animal: the saved
        appointment and its status code (200, or 202 with the note pending), or
        an error response."""
        audio_bytes = await request.body()
        if not audio_bytes:
            return JSONResponse({"error": "empty request body"}, status_code=400)

        timing = {
            "audio_bytes": len(audio_bytes),
            "audio_duration_ms": _audio_duration_ms(request),
            # The phone uploads m4a, the desktop WAV; the transcriber has to be told which.
            "audio_mime": transcription_mime(request.headers.get("content-type")),
            "transcription_provider": config.transcription_provider,
            "note_provider": config.note_provider,
        }
        started = time.perf_counter()

        # Transcribe first. A transcription failure is fatal (502) — there's
        # nothing worth persisting, and the client retries the whole upload.
        try:
            transcript = await _transcribe(audio_bytes, timing["audio_mime"])
        except NoSpeechError:
            # Nothing was said, so there's nothing to save. A 422 rather than a
            # 502: the provider worked, and the same audio would fail again.
            _track(
                request,
                "soap_generated",
                outcome="no_speech",
                failed_stage="transcription",
                exam_id=None,
                appointment_id=None,
                patient_count=None,
                transcribe_ms=_elapsed_ms(started),
                note_gen_ms=None,
                total_ms=_elapsed_ms(started),
                **timing,
            )
            _log_recording("no_speech", started, timing, transcript_words=0)
            return JSONResponse({"error": "no speech detected"}, status_code=422)
        except _PROVIDER_ERRORS as exc:
            _track(
                request,
                "soap_generated",
                outcome="failed",
                failed_stage="transcription",
                exam_id=None,
                appointment_id=None,
                patient_count=None,
                transcribe_ms=_elapsed_ms(started),
                note_gen_ms=None,
                total_ms=_elapsed_ms(started),
                **timing,
                **error_properties(exc),
            )
            _log_recording("failed", started, timing, error=type(exc).__name__)
            return _provider_error_response(exc)
        timing["transcribe_ms"] = _elapsed_ms(started)
        # Logged as a count only: far more words than the recording could hold
        # is how an invented transcript shows up.
        transcript_words = len(transcript.split())
        note_started = time.perf_counter()

        # With a good transcript in hand, generating the notes is the only thing
        # left that can fail. If it does, persist the appointment with its note
        # pending and return 202 so the client can retry note-gen alone -- no
        # re-transcription.
        try:
            result = await _generate(transcript)
        except _PROVIDER_ERRORS as exc:
            appointment = store.add_pending_appointment(transcript)
            _track(
                request,
                "soap_generated",
                outcome="note_pending",
                failed_stage="note_generation",
                exam_id=appointment.exams[0].id,
                appointment_id=appointment.id,
                patient_count=None,
                note_gen_ms=_elapsed_ms(note_started),
                total_ms=_elapsed_ms(started),
                **timing,
                **error_properties(exc),
            )
            _log_recording(
                "note_pending",
                started,
                timing,
                note_gen_ms=_elapsed_ms(note_started),
                error=type(exc).__name__,
                transcript_words=transcript_words,
            )
            return appointment, 202

        # Persist so the notes sync to every device (mobile + desktop history).
        appointment = store.add_appointment(result.transcript, result.notes)
        _track(
            request,
            "soap_generated",
            outcome="complete",
            exam_id=appointment.exams[0].id,
            appointment_id=appointment.id,
            patient_count=len(appointment.exams),
            note_gen_ms=_elapsed_ms(note_started),
            total_ms=_elapsed_ms(started),
            **timing,
        )
        _log_recording(
            "complete",
            started,
            timing,
            note_gen_ms=_elapsed_ms(note_started),
            patient_count=len(appointment.exams),
            transcript_words=transcript_words,
        )
        return appointment, 200

    async def _complete_pending(request: Request, exam: Exam) -> JSONResponse | Exam:
        """Generate the notes for a note-pending exam from its saved transcript (no
        audio, no re-transcription): the exam as it now stands, or an error."""
        started = time.perf_counter()
        try:
            result = await _generate(exam.transcript)
        except _PROVIDER_ERRORS as exc:
            _track(
                request,
                "pending_note_completed",
                exam_id=exam.id,
                appointment_id=exam.appointment_id,
                outcome="failed",
                note_gen_ms=_elapsed_ms(started),
                **error_properties(exc),
            )
            # Left pending so the client can retry.
            return _provider_error_response(exc)

        # Only writes if still pending: an edit saved while the note was
        # generating wins, and comes back in the response.
        updated = store.complete_pending(exam.id, result.notes)
        if updated is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)
        _track(
            request,
            "pending_note_completed",
            exam_id=exam.id,
            appointment_id=exam.appointment_id,
            outcome="complete",
            patient_count=len(result.notes),
            note_gen_ms=_elapsed_ms(started),
        )
        return updated

    async def _regenerate(request: Request, tracked: dict, transcript) -> JSONResponse | SoapResult:
        """Re-run note generation from a (hand-corrected) transcript, no audio and
        nothing saved: the vet reviews the notes and saves them, or not."""
        if not isinstance(transcript, str) or not transcript.strip():
            return JSONResponse({"error": "missing transcript"}, status_code=400)
        started = time.perf_counter()
        try:
            result = await _generate(transcript)
        except _PROVIDER_ERRORS as exc:
            _track(
                request,
                "note_regenerated",
                outcome="failed",
                note_gen_ms=_elapsed_ms(started),
                **tracked,
                **error_properties(exc),
            )
            return _provider_error_response(exc)
        _track(
            request,
            "note_regenerated",
            outcome="complete",
            note_gen_ms=_elapsed_ms(started),
            patient_count=len(result.notes),
            **tracked,
        )
        return result

    async def _json_body(request: Request) -> dict | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        if body is None:
            return {}
        return body if isinstance(body, dict) else None

    # --- Health -------------------------------------------------------------------

    @app.get("/api/health")
    async def health():
        # The phone's reachability check before each upload. No auth: a reply of any
        # kind means the backend is up, and this one says nothing else.
        return {"status": "ok"}

    # --- Appointments: one recording, one exam per animal ----------------------

    @app.post("/api/appointments")
    async def create_appointment(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        if _wants_async(request):
            return await _create_appointment_async(request)
        created = await _create_appointment(request)
        if isinstance(created, JSONResponse):
            return created
        appointment, status = created
        return JSONResponse(appointment.to_dict(), status_code=status)

    @app.post("/api/appointments/regenerate")
    async def regenerate_appointment(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        transcript = body.get("transcript", "")
        # Optional, for analytics only: which appointment is being regenerated.
        appointment_id = body.get("appointment_id")
        appointment_id = appointment_id if isinstance(appointment_id, str) and appointment_id else None
        appointment = store.get_appointment(appointment_id) if appointment_id else None
        tracked = {
            "appointment_id": appointment_id,
            "transcript_edited": (
                transcript != appointment.transcript if appointment is not None else None
            ),
        }
        result = await _regenerate(request, tracked, transcript)
        if isinstance(result, JSONResponse):
            return result
        if appointment is not None:
            regenerated_appointments.add(appointment.id)
            regenerated_exams.update(exam.id for exam in appointment.exams)
        return JSONResponse(
            {"transcript": result.transcript, "patients": [n.to_dict() for n in result.notes]}
        )

    @app.post("/api/appointments/{appointment_id}/notes")
    async def complete_appointment(appointment_id: str, request: Request):
        # Finish an appointment saved with its note pending (a 202). Idempotent:
        # an appointment that's no longer pending is returned as-is.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        appointment = store.get_appointment(appointment_id)
        if appointment is None:
            return JSONResponse({"error": "appointment not found"}, status_code=404)
        refused = _no_transcript_yet(appointment)
        if refused is not None:
            return refused
        pending = next((exam for exam in appointment.exams if exam.note_pending), None)
        if pending is None:
            _track(
                request,
                "pending_note_completed",
                exam_id=None,
                appointment_id=appointment_id,
                outcome="already_complete",
            )
            return JSONResponse(appointment.to_dict())
        completed = await _complete_pending(request, pending)
        if isinstance(completed, JSONResponse):
            return completed
        appointment = store.get_appointment(appointment_id)
        if appointment is None:
            return JSONResponse({"error": "appointment not found"}, status_code=404)
        return JSONResponse(appointment.to_dict())

    @app.post("/api/appointments/{appointment_id}/retry")
    async def retry_appointment(appointment_id: str, request: Request):
        # Process a failed async upload again from its saved audio.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        appointment = store.get_appointment(appointment_id)
        if appointment is None:
            return JSONResponse({"error": "appointment not found"}, status_code=404)
        if appointment.stage != "failed":
            return JSONResponse(
                {"error": "only a failed recording can be retried"}, status_code=409
            )
        restarted = store.restart_processing(appointment_id)
        if restarted is None:
            return JSONResponse({"error": "appointment not found"}, status_code=404)
        worker.submit(appointment_id)
        return JSONResponse(restarted.to_dict(), status_code=202)

    @app.get("/api/events")
    async def appointment_events(request: Request):
        # The phone keeps this open while it's waiting on async uploads: one
        # "appointment" event per recording that finishes processing. It starts
        # with "ready" once subscribed, so the phone re-reads what it's waiting
        # on only then and can't miss an event in between. Keepalive comments
        # let both ends notice a dead connection.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized

        async def stream():
            async with events.subscribe() as queue:
                yield format_sse_event(event="ready", data_str="{}")
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), events_keepalive_seconds)
                    except asyncio.TimeoutError:
                        yield KEEPALIVE_COMMENT
                        continue
                    yield format_sse_event(event="appointment", data_str=json.dumps(event))

        return EventSourceResponse(stream(), headers={"Cache-Control": "no-cache"})

    @app.get("/api/appointments")
    async def list_appointments(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        return JSONResponse(
            {"appointments": [a.to_dict() for a in store.list_appointments()]}
        )

    @app.get("/api/appointments/{appointment_id}")
    async def get_appointment(appointment_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        appointment = store.get_appointment(appointment_id)
        if appointment is None:
            return JSONResponse({"error": "appointment not found"}, status_code=404)
        return JSONResponse(appointment.to_dict())

    @app.put("/api/appointments/{appointment_id}")
    async def update_appointment(appointment_id: str, request: Request):
        # Save the vet's edits to the shared transcript and every animal's note.
        # The body is the whole appointment: exams with an id are updated, ones
        # without are added, and exams left out are deleted.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        edits = _parse_exam_edits(body)
        if isinstance(edits, str):
            return JSONResponse({"error": edits}, status_code=400)

        before = store.get_appointment(appointment_id)
        if before is not None and before.stage == "processing":
            # The worker is about to replace the placeholder with the real notes.
            return JSONResponse({"error": "recording still processing"}, status_code=409)
        try:
            after = store.update_appointment(
                appointment_id, transcript=body["transcript"], exams=edits
            )
        except ValueError:
            return JSONResponse(
                {"error": "exams must belong to this appointment, each at most once"},
                status_code=400,
            )
        if after is None or before is None:
            return JSONResponse({"error": "appointment not found"}, status_code=404)

        previous = {exam.id: exam for exam in before.exams}
        kept = [exam for exam in after.exams if exam.id in previous]
        removed = previous.keys() - {exam.id for exam in after.exams}
        for exam in kept:
            summary = edit_summary(previous[exam.id].to_dict(), exam.to_dict(), _NOTE_FIELDS)
            if summary["fields_changed"]:
                edited_exams.add(exam.id)
            _track(
                request,
                "note_saved",
                exam_id=exam.id,
                appointment_id=appointment_id,
                includes_regenerated_content=exam.id in regenerated_exams,
                **summary,
            )
        _track(
            request,
            "appointment_saved",
            appointment_id=appointment_id,
            patient_count=len(after.exams),
            exams_added=len(after.exams) - len(kept),
            exams_removed=len(removed),
            transcript_edited=after.transcript != before.transcript,
            includes_regenerated_content=appointment_id in regenerated_appointments,
        )
        regenerated_appointments.discard(appointment_id)
        regenerated_exams.difference_update(previous)
        edited_exams.difference_update(removed)
        return JSONResponse(after.to_dict())

    @app.delete("/api/appointments/{appointment_id}")
    async def delete_appointment(appointment_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        appointment = store.get_appointment(appointment_id)
        if appointment is None or not store.delete_appointment(appointment_id):
            return JSONResponse({"error": "appointment not found"}, status_code=404)
        _track(
            request,
            "appointment_deleted",
            appointment_id=appointment_id,
            patient_count=len(appointment.exams),
        )
        regenerated_appointments.discard(appointment_id)
        for exam in appointment.exams:
            regenerated_exams.discard(exam.id)
            edited_exams.discard(exam.id)
        return JSONResponse({"status": "deleted"})

    # --- Single exams (the desktop's endpoints) ------------------------------
    # Each exam is one animal of an appointment. The desktop records, edits and
    # injects one exam at a time; these read and write the same appointments.

    @app.post("/api/soap")
    async def create_soap_note(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        created = await _create_appointment(request)
        if isinstance(created, JSONResponse):
            return created
        appointment, status = created
        # desktop compat: the first animal's exam, flat. A 202's is the pending
        # placeholder, which the desktop finishes via /api/exams/{id}/note.
        return JSONResponse(appointment.exams[0].to_dict(), status_code=status)

    @app.post("/api/exams/{exam_id}/note")
    async def complete_pending_note(exam_id: str, request: Request):
        # Finish a partial exam: re-run note generation from its already-saved
        # transcript (no audio, no re-transcription) and persist the result.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized

        exam = store.get(exam_id)
        if exam is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)
        owner = store.get_appointment(exam.appointment_id)
        refused = _no_transcript_yet(owner) if owner is not None else None
        if refused is not None:
            return refused
        # Idempotent: clients retry this from offline queues, possibly long
        # after the vet filled the note in by hand. An exam that's no longer
        # pending is returned as-is -- never regenerated over the vet's edits.
        if not exam.note_pending:
            _track(
                request,
                "pending_note_completed",
                exam_id=exam_id,
                appointment_id=exam.appointment_id,
                outcome="already_complete",
            )
            return JSONResponse(exam.to_dict())
        completed = await _complete_pending(request, exam)
        if isinstance(completed, JSONResponse):
            return completed
        return JSONResponse(completed.to_dict())

    @app.post("/api/soap/regenerate")
    async def regenerate_soap_note(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        transcript = body.get("transcript", "")
        # Optional, for analytics only: which exam is being regenerated.
        exam_id = body.get("exam_id")
        exam_id = exam_id if isinstance(exam_id, str) and exam_id else None
        exam = store.get(exam_id) if exam_id else None
        tracked = {
            "exam_id": exam_id,
            "transcript_edited": transcript != exam.transcript if exam is not None else None,
        }
        result = await _regenerate(request, tracked, transcript)
        if isinstance(result, JSONResponse):
            return result
        if exam_id:
            regenerated_exams.add(exam_id)
        # desktop compat: the first animal's note flat at the top level.
        return JSONResponse(result.to_dict())

    @app.get("/api/history")
    async def list_history(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        return JSONResponse({"exams": [exam.to_dict() for exam in store.list()]})

    @app.get("/api/exams/{exam_id}")
    async def get_exam(exam_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        exam = store.get(exam_id)
        if exam is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)
        return JSONResponse(exam.to_dict())

    @app.put("/api/exams/{exam_id}")
    async def update_exam(exam_id: str, request: Request):
        # Save the vet's inline edits back to the authoritative record.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized

        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        body = body or {}

        missing = [f for f in _SOAP_FIELDS if not isinstance(body.get(f), str)]
        if missing:
            return JSONResponse(
                {"error": f"missing or invalid fields: {', '.join(missing)}"}, status_code=400
            )

        patient_name = body.get("patient_name")
        if patient_name is not None and not isinstance(patient_name, str):
            return JSONResponse({"error": "patient_name must be a string"}, status_code=400)
        # Optional; when sent (the desktop always sends it) it replaces the
        # appointment's shared transcript, for every animal in it.
        transcript = body.get("transcript")
        if transcript is not None and not isinstance(transcript, str):
            return JSONResponse({"error": "transcript must be a string"}, status_code=400)

        before = store.get(exam_id)
        exam = store.update(
            exam_id,
            subjective=body["subjective"],
            objective=body["objective"],
            assessment=body["assessment"],
            plan=body["plan"],
            transcript=transcript,
            patient_name=patient_name,
        )
        if exam is None or before is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)

        edits = edit_summary(before.to_dict(), exam.to_dict(), _NOTE_FIELDS)
        if edits["fields_changed"]:
            edited_exams.add(exam_id)
        _track(
            request,
            "note_saved",
            exam_id=exam_id,
            appointment_id=exam.appointment_id,
            includes_regenerated_content=exam_id in regenerated_exams,
            **edits,
        )
        regenerated_exams.discard(exam_id)
        return JSONResponse(exam.to_dict())

    @app.delete("/api/exams/{exam_id}")
    async def delete_exam(exam_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        exam = store.get(exam_id)
        if exam is None or not store.delete(exam_id):
            return JSONResponse({"error": "exam not found"}, status_code=404)
        _track(request, "exam_deleted", exam_id=exam_id, appointment_id=exam.appointment_id)
        regenerated_exams.discard(exam_id)
        edited_exams.discard(exam_id)
        return JSONResponse({"status": "deleted"})

    # --- Remote AVImark injection bridge ------------------------------------
    # The mobile app asks (POST .../inject) for an exam's note to be pasted into
    # AVImark on the exam-room PC. The desktop tray app polls
    # GET /api/injections/pending, does the injection (or shows the Safety
    # Flyout), then acks. The backend never touches AVImark itself; it only
    # relays the request so the phone and the PC don't need to reach each other.

    @app.post("/api/exams/{exam_id}/inject")
    async def request_injection(exam_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        if store.get(exam_id) is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)
        req = injection_queue.request(exam_id)
        # A repeat of the same note shows up as attempt_number > 1.
        _track(
            request,
            "injection_requested",
            exam_id=exam_id,
            request_id=req.id,
            attempt_number=injection_queue.request_count(exam_id),
            edited_before_inject=exam_id in edited_exams,
        )
        return JSONResponse(req.to_dict(), status_code=202)

    @app.get("/api/injections/pending")
    async def list_pending_injections(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        requests = []
        for req in injection_queue.pending():
            payload = req.to_dict()
            # Resolve the note fresh at poll time so any edits the vet made after
            # tapping Inject are reflected in what actually gets pasted.
            exam = store.get(req.exam_id)
            payload["exam"] = exam.to_dict() if exam is not None else None
            requests.append(payload)
        return JSONResponse({"requests": requests})

    @app.post("/api/injections/{request_id}/ack")
    async def ack_injection(request_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        try:
            body = await request.json()
        except ValueError:
            body = {}
        outcome = (body or {}).get("outcome", "injected")
        req = injection_queue.ack(request_id, outcome=outcome)
        if req is None:
            return JSONResponse({"error": "injection request not found"}, status_code=404)
        return JSONResponse(req.to_dict())

    return app
