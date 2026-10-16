"""The appointment API: one recording, one shared transcript, one exam per animal."""

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_app import FakePipeline
from vet_soap_notetaker_backend.app import create_app
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError
from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import ExamStore

BELLA = SoapNote(subjective="s1", objective="o1", assessment="a1", plan="p1", patient_name="Bella")
MAX = SoapNote(subjective="s2", objective="o2", assessment="a2", plan="p2", patient_name="Max")


@pytest.fixture
def make_client(make_config):
    def _make(pipeline=None, store=None, **config):
        store = store if store is not None else ExamStore()
        pipeline = pipeline or FakePipeline(notes=[BELLA, MAX], transcript="two dogs today")
        return TestClient(create_app(config=make_config(**config), pipeline=pipeline, store=store)), store

    return _make


def _exam_body(exam, **overrides):
    body = {k: exam[k] for k in ("id", "patient_name", "subjective", "objective", "assessment", "plan")}
    body.update(overrides)
    return body


# --- POST /api/appointments ----------------------------------------------------


def test_create_appointment_returns_one_exam_per_animal_and_the_shared_transcript(make_client):
    client, store = make_client()

    response = client.post("/api/appointments", content=b"RIFF....audio....")

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "two dogs today"
    assert body["note_pending"] is False
    assert [(e["patient_name"], e["plan"]) for e in body["exams"]] == [("Bella", "p1"), ("Max", "p2")]
    assert all(e["appointment_id"] == body["id"] for e in body["exams"])
    assert store.get_appointment(body["id"]).to_dict() == body


def test_create_appointment_returns_202_with_a_pending_placeholder_when_note_gen_fails(make_client):
    pipeline = FakePipeline(transcript="two dogs today", note_error=NoteParsingError("bad"))
    client, store = make_client(pipeline=pipeline)

    response = client.post("/api/appointments", content=b"RIFF")

    assert response.status_code == 202
    body = response.json()
    assert body["note_pending"] is True
    assert body["transcript"] == "two dogs today"
    [placeholder] = body["exams"]
    assert placeholder["note_pending"] is True
    assert placeholder["subjective"] == ""


def test_create_appointment_returns_502_and_saves_nothing_when_transcription_fails(make_client):
    pipeline = FakePipeline(transcribe_error=httpx.ConnectError("down"))
    client, store = make_client(pipeline=pipeline)

    response = client.post("/api/appointments", content=b"RIFF")

    assert response.status_code == 502
    assert response.json() == {"error": "upstream provider unreachable (ConnectError)"}
    assert store.list_appointments() == []


def test_create_appointment_returns_400_on_empty_body(make_client):
    client, _ = make_client()

    assert client.post("/api/appointments", content=b"").status_code == 400


# --- POST /api/appointments/{id}/notes ------------------------------------------


def test_complete_appointment_generates_every_animal_from_the_saved_transcript(make_client):
    pipeline = FakePipeline(transcript="two dogs today", note_error=NoteParsingError("bad"))
    client, store = make_client(pipeline=pipeline)
    appointment_id = client.post("/api/appointments", content=b"RIFF").json()["id"]
    pipeline.note_error = None
    pipeline.notes = [BELLA, MAX]

    response = client.post(f"/api/appointments/{appointment_id}/notes")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == appointment_id
    assert body["note_pending"] is False
    assert [e["patient_name"] for e in body["exams"]] == ["Bella", "Max"]
    assert pipeline.received_transcript == "two dogs today"


def test_complete_appointment_is_idempotent(make_client):
    pipeline = FakePipeline(transcript="t", note_error=NoteParsingError("bad"))
    client, store = make_client(pipeline=pipeline)
    appointment_id = client.post("/api/appointments", content=b"RIFF").json()["id"]
    pipeline.note_error = None
    pipeline.notes = [BELLA, MAX]

    first = client.post(f"/api/appointments/{appointment_id}/notes").json()
    pipeline.received_transcript = None
    second = client.post(f"/api/appointments/{appointment_id}/notes")

    assert second.status_code == 200
    assert second.json() == first
    # Already complete: no provider call.
    assert pipeline.received_transcript is None


def test_complete_appointment_returns_502_and_stays_pending_while_note_gen_fails(make_client):
    pipeline = FakePipeline(transcript="t", note_error=NoteParsingError("bad"))
    client, store = make_client(pipeline=pipeline)
    appointment_id = client.post("/api/appointments", content=b"RIFF").json()["id"]

    response = client.post(f"/api/appointments/{appointment_id}/notes")

    assert response.status_code == 502
    assert store.get_appointment(appointment_id).note_pending is True


def test_complete_appointment_returns_404_for_an_unknown_appointment(make_client):
    client, _ = make_client()

    assert client.post("/api/appointments/nope/notes").status_code == 404


# --- GET /api/appointments, GET/PUT/DELETE /api/appointments/{id} ---------------


def test_list_appointments_newest_first(make_client):
    client, store = make_client()
    first = store.add_appointment("t1", [BELLA])
    second = store.add_appointment("t2", [MAX])

    body = client.get("/api/appointments").json()

    assert [a["id"] for a in body["appointments"]] == [second.id, first.id]
    assert body["appointments"][0] == second.to_dict()


def test_get_appointment_returns_it_and_404_when_unknown(make_client):
    client, store = make_client()
    appointment = store.add_appointment("t", [BELLA, MAX])

    assert client.get(f"/api/appointments/{appointment.id}").json() == appointment.to_dict()
    assert client.get("/api/appointments/nope").status_code == 404


def test_update_appointment_saves_the_transcript_and_every_animal(make_client):
    client, store = make_client()
    appointment = store.add_appointment("two dogs", [BELLA, MAX]).to_dict()
    bella, max_ = appointment["exams"]

    response = client.put(
        f"/api/appointments/{appointment['id']}",
        json={
            "transcript": "corrected",
            "exams": [
                _exam_body(bella, plan="new plan"),
                {"patient_name": "Luna", "subjective": "s", "objective": "o",
                 "assessment": "a", "plan": "added"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "corrected"
    assert [(e["patient_name"], e["plan"]) for e in body["exams"]] == [
        ("Bella", "new plan"),
        ("Luna", "added"),
    ]
    assert body["exams"][0]["id"] == bella["id"]
    assert store.get(max_["id"]) is None
    assert store.get_appointment(appointment["id"]).to_dict() == body


@pytest.mark.parametrize(
    "body",
    [
        {"exams": []},
        {"transcript": 3, "exams": []},
        {"transcript": "t"},
        {"transcript": "t", "exams": []},
        {"transcript": "t", "exams": "Bella"},
        {"transcript": "t", "exams": ["Bella"]},
        {"transcript": "t", "exams": [{"subjective": "s", "objective": "o", "assessment": "a"}]},
        {"transcript": "t", "exams": [{"subjective": "s", "objective": "o", "assessment": "a",
                                       "plan": "p", "patient_name": 4}]},
        {"transcript": "t", "exams": [{"subjective": "s", "objective": "o", "assessment": "a",
                                       "plan": "p", "id": 4}]},
    ],
    ids=["no-transcript", "bad-transcript", "no-exams", "empty-exams", "exams-not-list",
         "exam-not-object", "missing-field", "bad-name", "bad-id"],
)
def test_update_appointment_rejects_a_malformed_body(make_client, body):
    client, store = make_client()
    appointment = store.add_appointment("t", [BELLA])

    response = client.put(f"/api/appointments/{appointment.id}", json=body)

    assert response.status_code == 400
    assert store.get_appointment(appointment.id) == appointment


def test_update_appointment_rejects_an_exam_from_another_appointment(make_client):
    client, store = make_client()
    one = store.add_appointment("one", [BELLA])
    other = store.add_appointment("other", [MAX])

    response = client.put(
        f"/api/appointments/{one.id}",
        json={"transcript": "t", "exams": [_exam_body(other.exams[0].to_dict())]},
    )

    assert response.status_code == 400
    assert store.get_appointment(one.id) == one
    assert store.get_appointment(other.id) == other


def test_update_appointment_returns_404_for_an_unknown_appointment(make_client):
    client, _ = make_client()

    response = client.put(
        "/api/appointments/nope",
        json={"transcript": "t", "exams": [{"subjective": "s", "objective": "o",
                                            "assessment": "a", "plan": "p"}]},
    )

    assert response.status_code == 404


def test_delete_appointment_removes_every_animal(make_client):
    client, store = make_client()
    appointment = store.add_appointment("t", [BELLA, MAX])

    response = client.delete(f"/api/appointments/{appointment.id}")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    assert store.list() == []
    assert client.delete(f"/api/appointments/{appointment.id}").status_code == 404


# --- POST /api/appointments/regenerate -------------------------------------------


def test_regenerate_appointment_returns_every_animal_without_saving(make_client):
    client, store = make_client()

    response = client.post("/api/appointments/regenerate", json={"transcript": "corrected"})

    assert response.status_code == 200
    assert response.json() == {
        "transcript": "corrected",
        "patients": [BELLA.to_dict(), MAX.to_dict()],
    }
    assert store.list_appointments() == []


def test_regenerate_appointment_rejects_a_blank_transcript(make_client):
    client, _ = make_client()

    assert client.post("/api/appointments/regenerate", json={"transcript": " "}).status_code == 400
    assert client.post("/api/appointments/regenerate", content=b"nope").status_code == 400


def test_regenerate_appointment_returns_502_when_note_gen_fails(make_client):
    client, _ = make_client(pipeline=FakePipeline(note_error=NoteParsingError("SECRET")))

    response = client.post("/api/appointments/regenerate", json={"transcript": "t"})

    assert response.status_code == 502
    assert "SECRET" not in response.text


# --- auth -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/api/appointments"),
        ("post", "/api/appointments/x/notes"),
        ("get", "/api/appointments"),
        ("get", "/api/appointments/x"),
        ("put", "/api/appointments/x"),
        ("delete", "/api/appointments/x"),
        ("post", "/api/appointments/regenerate"),
    ],
)
def test_every_appointment_endpoint_requires_the_bearer_token(make_client, method, path):
    client, _ = make_client(backend_api_key="secret")

    assert getattr(client, method)(path).status_code == 401


# --- the desktop's exam endpoints read and write the same appointments -----------


def test_desktop_soap_upload_is_an_appointment_too(make_client):
    client, store = make_client()

    exam = client.post("/api/soap", content=b"RIFF").json()

    appointment = client.get(f"/api/appointments/{exam['appointment_id']}").json()
    assert [e["id"] for e in appointment["exams"]][0] == exam["id"]
    assert [e["patient_name"] for e in appointment["exams"]] == ["Bella", "Max"]


def test_desktop_pending_upload_completes_into_its_appointment(make_client):
    pipeline = FakePipeline(transcript="two dogs", note_error=NoteParsingError("bad"))
    client, store = make_client(pipeline=pipeline)
    pending = client.post("/api/soap", content=b"RIFF")
    assert pending.status_code == 202
    pipeline.note_error = None
    pipeline.notes = [BELLA, MAX]

    exam = client.post(f"/api/exams/{pending.json()['id']}/note").json()

    appointment = store.get_appointment(exam["appointment_id"])
    assert [e.patient_name for e in appointment.exams] == ["Bella", "Max"]
    assert appointment.note_pending is False


def test_editing_the_transcript_on_one_exam_changes_it_for_every_animal(make_client):
    client, store = make_client()
    appointment = store.add_appointment("two dogs", [BELLA, MAX])
    bella, max_ = appointment.exams

    client.put(
        f"/api/exams/{bella.id}",
        json={"subjective": "s", "objective": "o", "assessment": "a", "plan": "p",
              "transcript": "corrected"},
    )

    assert client.get(f"/api/exams/{max_.id}").json()["transcript"] == "corrected"


def test_saving_an_exam_without_a_transcript_keeps_the_shared_one(make_client):
    client, store = make_client()
    exam = store.add_appointment("two dogs", [BELLA]).exams[0]

    response = client.put(
        f"/api/exams/{exam.id}",
        json={"subjective": "s", "objective": "o", "assessment": "a", "plan": "edited"},
    )

    assert response.status_code == 200
    assert response.json()["transcript"] == "two dogs"


def test_history_lists_every_animal_as_its_own_exam(make_client):
    client, store = make_client()
    store.add_appointment("one", [BELLA])
    store.add_appointment("two", [BELLA, MAX])

    exams = client.get("/api/history").json()["exams"]

    assert [(e["patient_name"], e["transcript"]) for e in exams] == [
        ("Bella", "two"), ("Max", "two"), ("Bella", "one"),
    ]


def test_each_animal_is_injected_on_its_own(make_client):
    client, store = make_client()
    bella, max_ = store.add_appointment("two dogs", [BELLA, MAX]).exams

    client.post(f"/api/exams/{max_.id}/inject")
    [request] = client.get("/api/injections/pending").json()["requests"]

    assert request["exam"]["patient_name"] == "Max"
    assert request["exam"]["plan"] == "p2"
