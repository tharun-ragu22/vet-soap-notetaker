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
from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import ExamStore
from vet_soap_notetaker_backend.llm.transcription import get_transcriber
from vet_soap_notetaker_backend.llm.transcription.gemini_transcriber import TranscriptionError

logger = logging.getLogger("vet_soap_notetaker_backend.app")

_NOTE_FIELDS = ("subjective", "objective", "assessment", "plan", "transcript")
# Placeholder note for an exam whose transcription succeeded but whose note
# generation failed; the empty fields are filled in by a later note-gen retry.
_EMPTY_NOTE = SoapNote(subjective="", objective="", assessment="", plan="")
# Client-supplied analytics headers longer than this are ignored rather than
# forwarded to PostHog.
_MAX_ANALYTICS_HEADER_LEN = 200


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


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

    @app.post("/api/soap")
    async def create_soap_note(request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized

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
                transcribe_ms=_elapsed_ms(started),
                note_gen_ms=None,
                total_ms=_elapsed_ms(started),
                **timing,
                **error_properties(exc),
            )
            return _provider_error_response(exc)
        timing["transcribe_ms"] = _elapsed_ms(started)
        note_started = time.perf_counter()

        # With a good transcript in hand, generating the note is the only thing
        # left that can fail. If it does, persist a *partial* exam (transcript
        # saved, note pending) and return 202 so the client can retry note-gen
        # alone via POST /api/exams/{id}/note -- no re-transcription.
        try:
            result = await _generate(transcript)
        except _PROVIDER_ERRORS as exc:
            partial = store.add(_EMPTY_NOTE, transcript, note_pending=True)
            _track(
                request,
                "soap_generated",
                outcome="note_pending",
                failed_stage="note_generation",
                exam_id=partial.id,
                note_gen_ms=_elapsed_ms(note_started),
                total_ms=_elapsed_ms(started),
                **timing,
                **error_properties(exc),
            )
            return JSONResponse(partial.to_dict(), status_code=202)

        # Persist so the notes sync to every device (mobile + desktop history):
        # one exam per animal, each with the recording's transcript. The response
        # is the first animal's exam -- the shape single-note clients read.
        exams = [
            store.add(note, result.transcript, patient_name=note.patient_name)
            for note in result.notes
        ]
        exam = exams[0]
        _track(
            request,
            "soap_generated",
            outcome="complete",
            exam_id=exam.id,
            note_gen_ms=_elapsed_ms(note_started),
            total_ms=_elapsed_ms(started),
            **timing,
        )
        return JSONResponse(exam.to_dict())

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
            _track(request, "pending_note_completed", exam_id=exam_id, outcome="already_complete")
            return JSONResponse(exam.to_dict())

        started = time.perf_counter()
        try:
            result = await _generate(exam.transcript)
        except _PROVIDER_ERRORS as exc:
            _track(
                request,
                "pending_note_completed",
                exam_id=exam_id,
                outcome="failed",
                note_gen_ms=_elapsed_ms(started),
                **error_properties(exc),
            )
            # Leave it pending so the client can retry.
            return _provider_error_response(exc)

        # Only writes if still pending: an edit saved while the note was
        # generating wins, and comes back in the response.
        updated = store.complete_pending(exam_id, result.notes)
        if updated is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)
        _track(
            request,
            "pending_note_completed",
            exam_id=exam_id,
            outcome="complete",
            note_gen_ms=_elapsed_ms(started),
        )
        return JSONResponse(updated.to_dict())

    @app.post("/api/soap/regenerate")
    async def regenerate_soap_note(request: Request):
        # Re-run note generation from a (hand-corrected) transcript, no audio.
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized

        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        transcript = (body or {}).get("transcript", "")
        if not isinstance(transcript, str) or not transcript.strip():
            return JSONResponse({"error": "missing transcript"}, status_code=400)
        # Optional, for analytics only: which exam is being regenerated.
        exam_id = (body or {}).get("exam_id")
        exam_id = exam_id if isinstance(exam_id, str) and exam_id else None
        exam = store.get(exam_id) if exam_id else None
        tracked = {
            "exam_id": exam_id,
            "transcript_edited": transcript != exam.transcript if exam is not None else None,
        }

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
            **tracked,
        )
        if exam_id:
            regenerated_exams.add(exam_id)
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

        missing = [f for f in _NOTE_FIELDS if not isinstance(body.get(f), str)]
        if missing:
            return JSONResponse(
                {"error": f"missing or invalid fields: {', '.join(missing)}"}, status_code=400
            )

        patient_name = body.get("patient_name")
        if patient_name is not None and not isinstance(patient_name, str):
            return JSONResponse({"error": "patient_name must be a string"}, status_code=400)

        before = store.get(exam_id)
        exam = store.update(
            exam_id,
            subjective=body["subjective"],
            objective=body["objective"],
            assessment=body["assessment"],
            plan=body["plan"],
            transcript=body["transcript"],
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
        if not store.delete(exam_id):
            return JSONResponse({"error": "exam not found"}, status_code=404)
        _track(request, "exam_deleted", exam_id=exam_id)
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
