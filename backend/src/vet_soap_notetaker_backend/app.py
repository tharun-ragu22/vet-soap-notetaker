import logging
import socket
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from vet_soap_notetaker_backend.analytics import (
    Analytics,
    edit_summary,
    error_properties,
    make_analytics,
)
from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.injection_queue import InjectionQueue
from vet_soap_notetaker_backend.llm.note_generation import get_note_generator
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError
from vet_soap_notetaker_backend.llm.pipeline import SoapPipeline
from vet_soap_notetaker_backend.schemas import SoapResult
from vet_soap_notetaker_backend.store import Appointment, Exam, ExamEdit, ExamStore
from vet_soap_notetaker_backend.llm.transcription import get_transcriber
from vet_soap_notetaker_backend.llm.transcription.gemini_transcriber import TranscriptionError

logger = logging.getLogger("vet_soap_notetaker_backend.app")

_SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")
_NOTE_FIELDS = (*_SOAP_FIELDS, "transcript")
# Client-supplied analytics headers longer than this are ignored rather than
# forwarded to PostHog.
_MAX_ANALYTICS_HEADER_LEN = 200


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
) -> FastAPI:
    config = config or BackendConfig.from_env()
    pipeline = pipeline or SoapPipeline(
        transcriber=get_transcriber(config),
        note_generator=get_note_generator(config),
    )
    store = store if store is not None else ExamStore()
    injection_queue = injection_queue if injection_queue is not None else InjectionQueue()
    analytics = analytics if analytics is not None else make_analytics(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
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
    async def _transcribe(audio_bytes: bytes) -> str:
        return await run_in_threadpool(pipeline.transcribe, audio_bytes)

    async def _generate(transcript: str):
        return await run_in_threadpool(pipeline.generate_from_transcript, transcript)

    _PROVIDER_ERRORS = (
        httpx.HTTPStatusError,
        httpx.RequestError,
        NoteParsingError,
        TranscriptionError,
    )

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
            "transcription_provider": config.transcription_provider,
            "note_provider": config.note_provider,
        }
        started = time.perf_counter()

        # Transcribe first. A transcription failure is fatal (502) — there's
        # nothing worth persisting, and the client retries the whole upload.
        try:
            transcript = await _transcribe(audio_bytes)
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
            return _provider_error_response(exc)
        timing["transcribe_ms"] = _elapsed_ms(started)
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

    # --- Appointments: one recording, one exam per animal ----------------------

    @app.post("/api/appointments")
    async def create_appointment(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
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
