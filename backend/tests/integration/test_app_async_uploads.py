"""POST /api/appointments with Prefer: respond-async -- reply once the audio is
safe, process it in the background, never duplicate a repeated upload."""

import hashlib
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_app import FakePipeline
from vet_soap_notetaker_backend.app import create_app
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError
from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import ExamStore

BELLA = SoapNote("s1", "o1", "a1", "p1", patient_name="Bella")
MAX = SoapNote("s2", "o2", "a2", "p2", patient_name="Max")
AUDIO = b"\x00\x01 phone m4a bytes"
ASYNC = {"Prefer": "respond-async", "Content-Type": "audio/m4a"}


class CountingPipeline(FakePipeline):
    def __init__(self, **kwargs):
        kwargs.setdefault("notes", [BELLA, MAX])
        kwargs.setdefault("transcript", "two dogs today")
        super().__init__(**kwargs)
        self.transcribe_calls = 0
        # Cleared to hold transcription until a test releases it, so "still
        # processing" can be observed without racing the worker.
        self.gate = threading.Event()
        self.gate.set()

    def transcribe(self, audio_bytes, mime_type="audio/wav"):
        self.transcribe_calls += 1
        assert self.gate.wait(timeout=5)
        return super().transcribe(audio_bytes, mime_type)


@pytest.fixture
def make_app(make_config, tmp_path):
    clients = []

    def _make(pipeline=None, **config):
        pipeline = pipeline or CountingPipeline()
        store = ExamStore()
        app = create_app(
            config=make_config(**config), pipeline=pipeline, store=store,
            audio_dir=tmp_path / "incoming",
        )
        client = TestClient(app)
        client.__enter__()  # runs the lifespan, which starts the worker
        clients.append(client)

        def drain():
            client.portal.call(app.state.worker.drain)

        return client, store, pipeline, drain

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def _upload(client, key="rec-1", audio=AUDIO, **headers):
    return client.post(
        "/api/appointments", content=audio, headers={**ASYNC, "Idempotency-Key": key, **headers}
    )


def test_async_upload_replies_202_processing_before_any_note_exists(make_app, tmp_path):
    client, store, pipeline, drain = make_app()

    response = _upload(client)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["transcript"] == ""
    saved = store.get_appointment(body["id"])
    assert saved.audio_sha256 == hashlib.sha256(AUDIO).hexdigest()
    assert saved.audio_mime == "audio/mp4"  # the phone's audio/m4a, normalised

    drain()
    done = client.get(f"/api/appointments/{body['id']}").json()
    assert done["status"] == "complete"
    assert [e["patient_name"] for e in done["exams"]] == ["Bella", "Max"]
    assert pipeline.received_mime == "audio/mp4"
    assert list((tmp_path / "incoming").iterdir()) == []


def test_repeating_an_upload_returns_the_same_appointment_without_reprocessing(make_app):
    client, store, pipeline, drain = make_app()
    pipeline.gate.clear()
    first = _upload(client).json()

    again_while_processing = _upload(client)
    pipeline.gate.set()
    drain()
    again_when_done = _upload(client)

    assert again_while_processing.status_code == 202
    assert again_while_processing.json()["id"] == first["id"]
    assert again_when_done.status_code == 200
    assert again_when_done.json()["id"] == first["id"]
    assert again_when_done.json()["status"] == "complete"
    assert pipeline.transcribe_calls == 1
    assert len(store.list_appointments()) == 1


def test_a_note_pending_repeat_replies_202(make_app):
    client, _, _, drain = make_app(CountingPipeline(note_error=NoteParsingError("bad")))
    first = _upload(client).json()
    drain()

    again = _upload(client)

    assert again.status_code == 202
    assert again.json()["id"] == first["id"]
    assert again.json()["status"] == "note_pending"


def test_a_key_reused_for_different_audio_is_refused(make_app):
    client, store, pipeline, drain = make_app()
    _upload(client)

    response = _upload(client, audio=b"some other recording")

    assert response.status_code == 409
    assert response.json() == {"error": "key already used for a different recording"}
    drain()
    assert pipeline.transcribe_calls == 1
    assert len(store.list_appointments()) == 1


def test_uploads_without_a_key_are_each_processed(make_app):
    client, store, _, drain = make_app()
    client.post("/api/appointments", content=AUDIO, headers=ASYNC)
    client.post("/api/appointments", content=AUDIO, headers=ASYNC)
    drain()
    assert len(store.list_appointments()) == 2


def test_an_overlong_key_is_refused(make_app):
    client, _, _, _ = make_app()
    response = _upload(client, key="k" * 129)
    assert response.status_code == 400


def test_an_empty_async_upload_is_refused(make_app):
    client, store, _, _ = make_app()
    assert _upload(client, audio=b"").status_code == 400
    assert store.list_appointments() == []


def test_without_prefer_the_upload_is_still_synchronous(make_app):
    client, _, pipeline, _ = make_app()

    response = client.post(
        "/api/appointments", content=AUDIO, headers={"Idempotency-Key": "rec-1"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert pipeline.transcribe_calls == 1


def test_async_upload_needs_auth(make_app):
    client, store, _, _ = make_app(backend_api_key="secret")
    assert _upload(client).status_code == 401
    assert store.list_appointments() == []


def test_retry_reprocesses_a_failed_appointment_from_its_saved_audio(make_app):
    pipeline = CountingPipeline(transcribe_error=httpx.ConnectError("down"))
    client, _, _, drain = make_app(pipeline)
    first = _upload(client).json()
    drain()
    assert client.get(f"/api/appointments/{first['id']}").json()["status"] == "failed"

    pipeline.transcribe_error = None
    response = client.post(f"/api/appointments/{first['id']}/retry")
    drain()

    assert response.status_code == 202
    assert response.json()["status"] == "processing"
    assert client.get(f"/api/appointments/{first['id']}").json()["status"] == "complete"
    assert pipeline.received_audio == AUDIO


def test_retry_refuses_an_appointment_that_has_not_failed(make_app):
    client, store, _, drain = make_app()
    first = _upload(client).json()
    drain()

    assert client.post(f"/api/appointments/{first['id']}/retry").status_code == 409
    assert client.post("/api/appointments/missing/retry").status_code == 404


def test_a_processing_appointment_cannot_be_edited_or_noted_until_done(make_app):
    pipeline = CountingPipeline()
    client, store, _, drain = make_app(pipeline)
    appointment, _ = store.create_processing("held", "sha", "audio/mp4")  # never submitted
    exam_id = appointment.exams[0].id
    edit = {"transcript": "t", "exams": [{"id": exam_id, "subjective": "s", "objective": "o",
                                          "assessment": "a", "plan": "p"}]}

    assert client.put(f"/api/appointments/{appointment.id}", json=edit).status_code == 409
    assert client.post(f"/api/appointments/{appointment.id}/notes").status_code == 409
    assert client.post(f"/api/exams/{exam_id}/note").status_code == 409
    assert pipeline.transcribe_calls == 0


def test_the_desktop_history_leaves_out_appointments_still_processing(make_app):
    client, _, pipeline, drain = make_app()
    pipeline.gate.clear()
    _upload(client)
    try:
        assert client.get("/api/history").json() == {"exams": []}
    finally:
        pipeline.gate.set()
        drain()
