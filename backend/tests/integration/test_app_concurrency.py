import asyncio
import threading

import httpx
import pytest

from vet_soap_notetaker_backend.app import create_app
from vet_soap_notetaker_backend.schemas import SoapNote, SoapResult
from vet_soap_notetaker_backend.store import ExamStore

NOTE = SoapNote(subjective="s", objective="o", assessment="a", plan="p")


class BlockingPipeline:
    """Blocks inside one chosen stage until released, like a slow provider call.

    Blocks on a threading.Event rather than sleeping, so the tests don't depend
    on timing: they release the stage themselves once they've checked that other
    requests were served in the meantime. The wait has a timeout as a safety
    valve, so a regression fails the test instead of hanging the suite.
    """

    def __init__(self, block_in):
        self.block_in = block_in
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = False

    def _maybe_block(self, stage):
        if stage == self.block_in:
            self.entered.set()
            self.release.wait(timeout=5)
            self.finished = True

    def transcribe(self, audio_bytes, mime_type="audio/wav"):
        self._maybe_block("transcribe")
        return "owner reports vomiting"

    def generate_from_transcript(self, transcript):
        self._maybe_block("generate")
        return SoapResult(notes=[NOTE], transcript=transcript)


def _create_soap(client, store):
    return client.post("/api/soap", content=b"RIFF....audio....")


def _complete_pending_note(client, store):
    partial = store.add(
        SoapNote(subjective="", objective="", assessment="", plan=""),
        "owner reports vomiting",
        note_pending=True,
    )
    return client.post(f"/api/exams/{partial.id}/note")


def _regenerate(client, store):
    return client.post("/api/soap/regenerate", json={"transcript": "owner reports vomiting"})


def _create_appointment(client, store):
    return client.post("/api/appointments", content=b"RIFF....audio....")


def _complete_pending_appointment(client, store):
    pending = store.add_pending_appointment("owner reports vomiting")
    return client.post(f"/api/appointments/{pending.id}/notes")


def _regenerate_appointment(client, store):
    return client.post(
        "/api/appointments/regenerate", json={"transcript": "owner reports vomiting"}
    )


@pytest.mark.parametrize(
    ("block_in", "slow_request"),
    [
        ("transcribe", _create_soap),
        ("generate", _create_soap),
        ("generate", _complete_pending_note),
        ("generate", _regenerate),
        ("transcribe", _create_appointment),
        ("generate", _create_appointment),
        ("generate", _complete_pending_appointment),
        ("generate", _regenerate_appointment),
    ],
    ids=[
        "soap-transcribe", "soap-note-gen", "complete-pending-note", "regenerate",
        "appointment-transcribe", "appointment-note-gen", "complete-pending-appointment",
        "regenerate-appointment",
    ],
)
async def test_other_requests_are_served_while_a_provider_call_is_in_flight(
    make_config, block_in, slow_request
):
    # Provider calls block (sync httpx, retry sleeps, Files API polling). If a
    # handler runs one on the event loop, every other request -- the desktop's
    # injection poll, History, saves -- stalls behind it until it returns.
    pipeline = BlockingPipeline(block_in)
    store = ExamStore()
    app = create_app(config=make_config(), pipeline=pipeline, store=store)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slow = asyncio.create_task(slow_request(client, store))
        try:
            assert await asyncio.to_thread(pipeline.entered.wait, 5)

            history = await client.get("/api/history")
            pending = await client.get("/api/injections/pending")

            assert history.status_code == 200
            assert pending.status_code == 200
            # Served while the slow call was still blocked, not after it finished.
            assert pipeline.finished is False
        finally:
            pipeline.release.set()
            response = await slow

    assert response.status_code == 200


def test_requests_are_served_while_the_worker_processes_an_async_upload(make_config, tmp_path):
    # The worker runs on the event loop too; its provider calls must not stall it.
    pipeline = BlockingPipeline("transcribe")
    app = create_app(
        config=make_config(), pipeline=pipeline, store=ExamStore(), audio_dir=tmp_path
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        upload = client.post(
            "/api/appointments", content=b"m4a", headers={"Prefer": "respond-async"}
        )
        try:
            assert upload.status_code == 202
            assert pipeline.entered.wait(5)
            assert client.get("/api/history").status_code == 200
            assert client.get(f"/api/appointments/{upload.json()['id']}").json()["status"] == (
                "processing"
            )
            assert pipeline.finished is False
        finally:
            pipeline.release.set()
            client.portal.call(app.state.worker.drain)
