"""AppointmentWorker: processes uploaded audio in the background (Prefer: respond-async)."""

import httpx
import pytest

from vet_soap_notetaker_backend.events import EventHub
from vet_soap_notetaker_backend.jobs import AppointmentWorker
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError
from vet_soap_notetaker_backend.llm.transcription import NoSpeechError
from vet_soap_notetaker_backend.schemas import SoapNote, SoapResult
from vet_soap_notetaker_backend.store import ExamStore, JsonFileExamStore

BELLA = SoapNote("s1", "o1", "a1", "p1", patient_name="Bella")
MAX = SoapNote("s2", "o2", "a2", "p2", patient_name="Max")
UNNAMED = SoapNote("s", "o", "a", "p")
AUDIO = b"\x01\x02audio"
PROVIDER_ERRORS = (httpx.HTTPStatusError, httpx.RequestError, NoteParsingError)


class FakeSteps:
    def __init__(self, transcript="two dogs", notes=(BELLA, MAX), transcribe_error=None,
                 note_error=None):
        self.transcript = transcript
        self.notes = list(notes)
        self.transcribe_error = transcribe_error
        self.note_error = note_error
        self.transcribed = []

    async def transcribe(self, audio, mime):
        self.transcribed.append((audio, mime))
        if self.transcribe_error is not None:
            raise self.transcribe_error
        return self.transcript

    async def generate(self, transcript):
        if self.note_error is not None:
            raise self.note_error
        return SoapResult(notes=self.notes, transcript=transcript)


def make_worker(tmp_path, steps=None, store=None, outcomes=None):
    steps = steps or FakeSteps()
    store = store if store is not None else ExamStore()
    hub = EventHub()
    worker = AppointmentWorker(
        store=store,
        hub=hub,
        audio_dir=tmp_path / "incoming",
        transcribe=steps.transcribe,
        generate=steps.generate,
        provider_errors=PROVIDER_ERRORS,
        on_outcome=(lambda *args: outcomes.append(args)) if outcomes is not None else None,
    )
    return worker, store, hub, steps


async def upload(worker, store, key="key-1", mime="audio/mp4"):
    appointment, _ = store.create_processing(key, "sha", mime)
    await worker.save_audio(appointment, AUDIO)
    worker.submit(appointment.id)
    return appointment


async def process(worker, hub, store, **kwargs):
    async with hub.subscribe() as events:
        appointment = await upload(worker, store, **kwargs)
        await worker.drain()
        published = [events.get_nowait() for _ in range(events.qsize())]
    return store.get_appointment(appointment.id), published


async def test_success_saves_the_notes_and_announces_the_animals(tmp_path):
    worker, store, hub, steps = make_worker(tmp_path)
    worker.start()
    try:
        appointment, events = await process(worker, hub, store)
    finally:
        await worker.stop()

    assert appointment.status == "complete"
    assert appointment.transcript == "two dogs"
    assert [e.patient_name for e in appointment.exams] == ["Bella", "Max"]
    assert steps.transcribed == [(AUDIO, "audio/mp4")]
    assert events == [
        {"id": appointment.id, "status": "complete", "patient_names": ["Bella", "Max"]}
    ]
    # The transcript is safe in the store: the audio is no longer needed.
    assert list((tmp_path / "incoming").iterdir()) == []


async def test_unnamed_animals_are_left_out_of_the_names(tmp_path):
    worker, store, hub, _ = make_worker(tmp_path, FakeSteps(notes=[UNNAMED]))
    worker.start()
    try:
        _, events = await process(worker, hub, store)
    finally:
        await worker.stop()
    assert events[0]["patient_names"] == []


async def test_a_transcription_failure_keeps_the_audio_for_a_retry(tmp_path):
    error = httpx.ConnectError("boom")
    worker, store, hub, _ = make_worker(tmp_path, FakeSteps(transcribe_error=error))
    worker.start()
    try:
        appointment, events = await process(worker, hub, store)
    finally:
        await worker.stop()

    assert appointment.status == "failed"
    assert events == [{"id": appointment.id, "status": "failed", "patient_names": []}]
    assert len(list((tmp_path / "incoming").iterdir())) == 1


async def test_a_note_generation_failure_leaves_the_note_pending(tmp_path):
    worker, store, hub, _ = make_worker(tmp_path, FakeSteps(note_error=NoteParsingError("x")))
    worker.start()
    try:
        appointment, events = await process(worker, hub, store)
    finally:
        await worker.stop()

    assert appointment.status == "note_pending"
    assert appointment.transcript == "two dogs"
    assert events[0]["status"] == "note_pending"
    assert list((tmp_path / "incoming").iterdir()) == []


async def test_no_speech_is_terminal_and_drops_the_audio(tmp_path):
    worker, store, hub, _ = make_worker(tmp_path, FakeSteps(transcribe_error=NoSpeechError()))
    worker.start()
    try:
        appointment, events = await process(worker, hub, store)
    finally:
        await worker.stop()

    assert appointment.status == "no_speech"
    assert events[0]["status"] == "no_speech"
    assert list((tmp_path / "incoming").iterdir()) == []


async def test_an_unexpected_error_fails_the_appointment_and_the_worker_keeps_going(tmp_path):
    worker, store, hub, steps = make_worker(tmp_path, FakeSteps(transcribe_error=RuntimeError("?")))
    worker.start()
    try:
        first, _ = await process(worker, hub, store, key="k1")
        steps.transcribe_error = None
        second, _ = await process(worker, hub, store, key="k2")
    finally:
        await worker.stop()

    assert first.status == "failed"
    assert second.status == "complete"


async def test_an_appointment_deleted_while_processing_is_not_recreated(tmp_path):
    worker, store, hub, _ = make_worker(tmp_path)
    appointment = await upload(worker, store)
    store.delete_appointment(appointment.id)
    worker.start()
    try:
        await worker.drain()
    finally:
        await worker.stop()

    assert store.list_appointments() == []
    assert list((tmp_path / "incoming").iterdir()) == []


async def test_resume_picks_up_processing_appointments_after_a_restart(tmp_path):
    path = tmp_path / "exams.json"
    before, store, _, _ = make_worker(tmp_path, store=JsonFileExamStore(path))
    appointment = await upload(before, store)  # never processed: the backend "restarted"
    orphan = tmp_path / "incoming" / "gone.m4a"
    orphan.write_bytes(b"left over")

    worker, store, hub, steps = make_worker(tmp_path, store=JsonFileExamStore(path))
    worker.resume()
    worker.start()
    try:
        await worker.drain()
    finally:
        await worker.stop()

    assert store.get_appointment(appointment.id).status == "complete"
    assert steps.transcribed == [(AUDIO, "audio/mp4")]
    assert not orphan.exists()


async def test_missing_audio_fails_the_appointment(tmp_path):
    worker, store, hub, _ = make_worker(tmp_path)
    appointment, _ = store.create_processing("k", "sha", "audio/mp4")
    worker.submit(appointment.id)
    worker.start()
    try:
        await worker.drain()
    finally:
        await worker.stop()
    assert store.get_appointment(appointment.id).status == "failed"


@pytest.mark.parametrize(
    ("steps", "outcome"),
    [
        (FakeSteps(), "complete"),
        (FakeSteps(transcribe_error=httpx.ConnectError("x")), "failed"),
        (FakeSteps(note_error=NoteParsingError("x")), "note_pending"),
        (FakeSteps(transcribe_error=NoSpeechError()), "no_speech"),
    ],
)
async def test_each_outcome_is_reported_with_timings_and_never_a_message(tmp_path, steps, outcome):
    outcomes = []
    worker, store, hub, _ = make_worker(tmp_path, steps, outcomes=outcomes)
    worker.start()
    try:
        appointment, _ = await process(worker, hub, store)
    finally:
        await worker.stop()

    [(appointment_id, reported, info)] = outcomes
    assert (appointment_id, reported) == (appointment.id, outcome)
    assert "transcribe_ms" in info
    assert all(not isinstance(v, str) or v in ("ConnectError", "NoteParsingError")
               for v in info.values())
