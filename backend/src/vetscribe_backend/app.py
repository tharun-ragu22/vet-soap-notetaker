import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vetscribe_backend.config import BackendConfig
from vetscribe_backend.injection_queue import InjectionQueue
from vetscribe_backend.llm.note_generation import get_note_generator
from vetscribe_backend.llm.note_generation.parsing import NoteParsingError
from vetscribe_backend.llm.pipeline import SoapPipeline
from vetscribe_backend.store import ExamStore
from vetscribe_backend.llm.transcription import get_transcriber
from vetscribe_backend.llm.transcription.gemini_transcriber import TranscriptionError

_NOTE_FIELDS = ("subjective", "objective", "assessment", "plan", "transcript")


def create_app(
    config: BackendConfig | None = None,
    pipeline: SoapPipeline | None = None,
    store: ExamStore | None = None,
    injection_queue: InjectionQueue | None = None,
) -> FastAPI:
    config = config or BackendConfig.from_env()
    pipeline = pipeline or SoapPipeline(
        transcriber=get_transcriber(config),
        note_generator=get_note_generator(config),
    )
    store = store if store is not None else ExamStore()
    injection_queue = injection_queue if injection_queue is not None else InjectionQueue()

    app = FastAPI()

    def _unauthorized(request: Request) -> JSONResponse | None:
        if not config.backend_api_key:
            return None
        expected = f"Bearer {config.backend_api_key}"
        if request.headers.get("authorization") != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    def _provider_error_response(exc: Exception) -> JSONResponse:
        # Map every provider-level failure to a clean 502 rather than a raw 500
        # traceback. New provider failure modes belong in this tuple.
        if isinstance(exc, httpx.HTTPStatusError):
            return JSONResponse({"error": f"upstream provider error: {exc}"}, status_code=502)
        if isinstance(exc, httpx.RequestError):
            return JSONResponse({"error": f"upstream request failed: {exc}"}, status_code=502)
        return JSONResponse({"error": str(exc)}, status_code=502)

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

        try:
            result = pipeline.process(audio_bytes)
        except _PROVIDER_ERRORS as exc:
            return _provider_error_response(exc)

        # Persist so the note syncs to every device (mobile + desktop history).
        exam = store.add(
            result.note, result.transcript, patient_name=result.note.patient_name
        )
        return JSONResponse(exam.to_dict())

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

        try:
            result = pipeline.generate_from_transcript(transcript)
        except _PROVIDER_ERRORS as exc:
            return _provider_error_response(exc)

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

        exam = store.update(
            exam_id,
            subjective=body["subjective"],
            objective=body["objective"],
            assessment=body["assessment"],
            plan=body["plan"],
            transcript=body["transcript"],
            patient_name=patient_name,
        )
        if exam is None:
            return JSONResponse({"error": "exam not found"}, status_code=404)
        return JSONResponse(exam.to_dict())

    @app.delete("/api/exams/{exam_id}")
    async def delete_exam(exam_id: str, request: Request):
        unauthorized = _unauthorized(request)
        if unauthorized is not None:
            return unauthorized
        if not store.delete(exam_id):
            return JSONResponse({"error": "exam not found"}, status_code=404)
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
