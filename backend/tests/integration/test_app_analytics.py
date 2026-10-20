"""What the backend reports to analytics (PostHog) for each endpoint.

Every event is metadata only -- ids, durations, counts, field names, how much a
box changed -- never audio, transcripts, note text or patient names. The last
test drives every endpoint with a sentinel patient and checks it never leaks.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.fakes import RecordingAnalytics
from vet_soap_notetaker_backend.llm.transcription import NoSpeechError
from tests.integration.test_app import FakePipeline
from vet_soap_notetaker_backend.app import create_app
from vet_soap_notetaker_backend.injection_queue import InjectionQueue
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError
from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import ExamStore

SENTINEL = "ZZ_PATIENT_SENTINEL"


def _note(text="a", patient_name=None):
    return SoapNote(
        subjective=f"s {text}",
        objective=f"o {text}",
        assessment=f"a {text}",
        plan=f"p {text}",
        patient_name=patient_name,
    )


@pytest.fixture
def setup(make_config):
    def _setup(pipeline=None, store=None, **config_overrides):
        tracker = RecordingAnalytics()
        store = store if store is not None else ExamStore()
        app = create_app(
            config=make_config(
                **{
                    "transcription_provider": "gemini",
                    "note_provider": "ollama",
                    "analytics_user_id": "clinic-default",
                    **config_overrides,
                }
            ),
            pipeline=pipeline or FakePipeline(note=_note(), transcript="owner reports vomiting"),
            store=store,
            injection_queue=InjectionQueue(),
            analytics=tracker,
        )
        return TestClient(app), tracker, store

    return _setup


CLIENT_HEADERS = {
    "X-POSTHOG-DISTINCT-ID": "demo-vet-1",
    "X-POSTHOG-SESSION-ID": "session-123",
    "X-VSN-Client": "mobile",
}


def _saved_body(exam, **overrides):
    body = {
        "subjective": exam["subjective"],
        "objective": exam["objective"],
        "assessment": exam["assessment"],
        "plan": exam["plan"],
        "transcript": exam["transcript"],
    }
    body.update(overrides)
    return body


# --- identity -------------------------------------------------------------


def test_events_are_attributed_to_the_client_supplied_distinct_id(setup):
    client, tracker, _ = setup()

    client.post("/api/soap", content=b"RIFF", headers=CLIENT_HEADERS)

    event = tracker.only("soap_generated")
    assert event["distinct_id"] == "demo-vet-1"
    assert event["properties"]["$session_id"] == "session-123"
    assert event["properties"]["source_app"] == "mobile"


def test_events_fall_back_to_the_configured_user_id_without_a_client_id(setup):
    client, tracker, _ = setup()

    client.post("/api/soap", content=b"RIFF")

    event = tracker.only("soap_generated")
    assert event["distinct_id"] == "clinic-default"
    assert "$session_id" not in event["properties"]
    assert event["properties"]["source_app"] == "unknown"


def test_events_fall_back_to_a_backend_id_when_nothing_is_configured(setup):
    client, tracker, _ = setup(analytics_user_id="")

    client.post("/api/soap", content=b"RIFF")

    assert tracker.only("soap_generated")["distinct_id"].startswith("backend-")


def test_overlong_client_ids_are_ignored(setup):
    client, tracker, _ = setup()

    client.post("/api/soap", content=b"RIFF", headers={"X-POSTHOG-DISTINCT-ID": "x" * 500})

    assert tracker.only("soap_generated")["distinct_id"] == "clinic-default"


# --- Q1: how long each meeting took to transcribe -----------------------


def test_soap_generated_reports_timings_audio_and_providers(setup):
    client, tracker, _ = setup()

    response = client.post(
        "/api/soap",
        content=b"RIFF....audio....",
        headers={**CLIENT_HEADERS, "X-Audio-Duration-Ms": "93500"},
    )

    props = tracker.only("soap_generated")["properties"]
    assert props["outcome"] == "complete"
    assert props["exam_id"] == response.json()["id"]
    assert props["audio_duration_ms"] == 93500
    assert props["audio_bytes"] == len(b"RIFF....audio....")
    assert props["transcription_provider"] == "gemini"
    assert props["note_provider"] == "ollama"
    for key in ("transcribe_ms", "note_gen_ms", "total_ms"):
        assert isinstance(props[key], int) and props[key] >= 0


def test_soap_generated_reports_the_audio_format(setup):
    client, tracker, _ = setup()

    client.post("/api/appointments", content=b"audio", headers={"Content-Type": "audio/m4a"})

    assert tracker.only("soap_generated")["properties"]["audio_mime"] == "audio/mp4"


def test_soap_generated_ignores_an_unparseable_audio_duration(setup):
    client, tracker, _ = setup()

    client.post("/api/soap", content=b"RIFF", headers={"X-Audio-Duration-Ms": "lots"})

    assert tracker.only("soap_generated")["properties"]["audio_duration_ms"] is None


def test_soap_generated_reports_note_pending_on_a_202(setup):
    client, tracker, _ = setup(
        pipeline=FakePipeline(transcript="t", note_error=NoteParsingError("bad json"))
    )

    response = client.post("/api/soap", content=b"RIFF")

    assert response.status_code == 202
    props = tracker.only("soap_generated")["properties"]
    assert props["outcome"] == "note_pending"
    assert props["exam_id"] == response.json()["id"]
    assert props["error_type"] == "NoteParsingError"
    assert isinstance(props["transcribe_ms"], int)
    assert isinstance(props["note_gen_ms"], int)


def test_soap_generated_reports_a_failed_transcription(setup):
    client, tracker, _ = setup(
        pipeline=FakePipeline(transcribe_error=httpx.ConnectError("boom"))
    )

    response = client.post("/api/soap", content=b"RIFF")

    assert response.status_code == 502
    props = tracker.only("soap_generated")["properties"]
    assert props["outcome"] == "failed"
    assert props["failed_stage"] == "transcription"
    assert props["error_type"] == "ConnectError"
    assert props["exam_id"] is None
    assert props["note_gen_ms"] is None


def test_soap_generated_reports_a_recording_with_no_speech(setup):
    client, tracker, _ = setup(pipeline=FakePipeline(transcribe_error=NoSpeechError()))

    response = client.post("/api/appointments", content=b"RIFF")

    assert response.status_code == 422
    props = tracker.only("soap_generated")["properties"]
    assert props["outcome"] == "no_speech"
    assert props["failed_stage"] == "transcription"
    assert props["appointment_id"] is None


def test_pending_note_completed_reports_timing_and_outcome(setup):
    pipeline = FakePipeline(transcript="t", note_error=NoteParsingError("bad json"))
    client, tracker, _ = setup(pipeline=pipeline)
    exam_id = client.post("/api/soap", content=b"RIFF").json()["id"]

    client.post(f"/api/exams/{exam_id}/note")
    pipeline.note_error = None
    pipeline.notes = [_note()]
    client.post(f"/api/exams/{exam_id}/note")
    client.post(f"/api/exams/{exam_id}/note")

    outcomes = [e["properties"]["outcome"] for e in tracker.named("pending_note_completed")]
    assert outcomes == ["failed", "complete", "already_complete"]
    for event in tracker.named("pending_note_completed"):
        assert event["properties"]["exam_id"] == exam_id
    assert isinstance(tracker.named("pending_note_completed")[1]["properties"]["note_gen_ms"], int)


# --- several animals in one appointment -------------------------------------


TWO = [_note("bella", "Bella"), _note("max", "Max")]


def test_soap_generated_reports_the_appointment_and_how_many_animals(setup):
    client, tracker, _ = setup(pipeline=FakePipeline(notes=TWO, transcript="t"))

    exam = client.post("/api/soap", content=b"RIFF").json()
    appointment = client.post("/api/appointments", content=b"RIFF").json()

    first, second = tracker.named("soap_generated")
    assert first["properties"]["patient_count"] == 2
    assert first["properties"]["appointment_id"] == exam["appointment_id"]
    assert second["properties"]["patient_count"] == 2
    assert second["properties"]["appointment_id"] == appointment["id"]
    assert second["properties"]["exam_id"] == appointment["exams"][0]["id"]


def test_soap_generated_has_no_patient_count_until_the_note_exists(setup):
    client, tracker, _ = setup(
        pipeline=FakePipeline(transcript="t", note_error=NoteParsingError("bad json"))
    )

    appointment = client.post("/api/appointments", content=b"RIFF").json()

    props = tracker.only("soap_generated")["properties"]
    assert props["outcome"] == "note_pending"
    assert props["patient_count"] is None
    assert props["appointment_id"] == appointment["id"]


def test_pending_appointment_completed_reports_the_appointment_and_animals(setup):
    pipeline = FakePipeline(transcript="t", note_error=NoteParsingError("bad json"))
    client, tracker, _ = setup(pipeline=pipeline)
    appointment = client.post("/api/appointments", content=b"RIFF").json()
    pipeline.note_error = None
    pipeline.notes = TWO

    client.post(f"/api/appointments/{appointment['id']}/notes")
    client.post(f"/api/appointments/{appointment['id']}/notes")

    events = tracker.named("pending_note_completed")
    assert [e["properties"]["outcome"] for e in events] == ["complete", "already_complete"]
    assert all(e["properties"]["appointment_id"] == appointment["id"] for e in events)
    assert events[0]["properties"]["patient_count"] == 2


def test_appointment_regenerated_reports_animals_and_transcript_edits(setup):
    client, tracker, _ = setup(pipeline=FakePipeline(notes=TWO, transcript="t"))
    appointment = client.post("/api/appointments", content=b"RIFF").json()

    client.post("/api/appointments/regenerate",
                json={"transcript": "t", "appointment_id": appointment["id"]})
    client.post("/api/appointments/regenerate",
                json={"transcript": "corrected", "appointment_id": appointment["id"]})

    events = tracker.named("note_regenerated")
    assert [e["properties"]["transcript_edited"] for e in events] == [False, True]
    assert all(e["properties"]["appointment_id"] == appointment["id"] for e in events)
    assert all(e["properties"]["patient_count"] == 2 for e in events)


def test_appointment_saved_reports_counts_and_each_animals_edits(setup):
    client, tracker, _ = setup(pipeline=FakePipeline(notes=TWO, transcript="t"))
    appointment = client.post("/api/appointments", content=b"RIFF").json()
    bella, max_ = appointment["exams"]
    client.post("/api/appointments/regenerate",
                json={"transcript": "t", "appointment_id": appointment["id"]})

    client.put(f"/api/appointments/{appointment['id']}", json={
        "transcript": "corrected",
        "exams": [{**bella, "plan": "rewritten"},
                  {**max_, "id": None, "patient_name": "Luna"}],
    })

    props = tracker.only("appointment_saved")["properties"]
    assert props["appointment_id"] == appointment["id"]
    assert props["patient_count"] == 2
    assert props["exams_added"] == 1
    assert props["exams_removed"] == 1
    assert props["transcript_edited"] is True
    assert props["includes_regenerated_content"] is True
    saved = tracker.only("note_saved")["properties"]
    assert saved["exam_id"] == bella["id"]
    assert saved["appointment_id"] == appointment["id"]
    assert saved["fields_changed"] == ["plan", "transcript"]


def test_an_animal_edited_in_an_appointment_counts_as_edited_before_inject(setup):
    client, tracker, _ = setup(pipeline=FakePipeline(notes=TWO, transcript="t"))
    appointment = client.post("/api/appointments", content=b"RIFF").json()
    bella, max_ = appointment["exams"]

    client.put(f"/api/appointments/{appointment['id']}", json={
        "transcript": "t", "exams": [{**bella, "plan": "edited"}, max_],
    })
    client.post(f"/api/exams/{bella['id']}/inject")
    client.post(f"/api/exams/{max_['id']}/inject")

    flags = [e["properties"]["edited_before_inject"] for e in tracker.named("injection_requested")]
    assert flags == [True, False]


def test_appointment_deleted_is_reported(setup):
    client, tracker, _ = setup(pipeline=FakePipeline(notes=TWO, transcript="t"))
    appointment = client.post("/api/appointments", content=b"RIFF").json()

    client.delete(f"/api/appointments/{appointment['id']}")
    client.delete(f"/api/appointments/{appointment['id']}")

    props = tracker.only("appointment_deleted")["properties"]
    assert props == {**props, "appointment_id": appointment["id"], "patient_count": 2}


# --- Q2: did he like the notes ---------------------------------------------


def test_note_regenerated_reports_the_exam_and_whether_the_transcript_was_edited(setup):
    client, tracker, _ = setup()
    exam = client.post("/api/soap", content=b"RIFF").json()

    client.post("/api/soap/regenerate", json={"transcript": exam["transcript"], "exam_id": exam["id"]})
    client.post("/api/soap/regenerate", json={"transcript": "corrected", "exam_id": exam["id"]})
    client.post("/api/soap/regenerate", json={"transcript": "no exam id"})

    events = tracker.named("note_regenerated")
    assert [e["properties"]["exam_id"] for e in events] == [exam["id"], exam["id"], None]
    assert [e["properties"]["transcript_edited"] for e in events] == [False, True, None]
    assert all(e["properties"]["outcome"] == "complete" for e in events)
    assert all(isinstance(e["properties"]["note_gen_ms"], int) for e in events)


def test_note_regenerated_reports_a_failure(setup):
    pipeline = FakePipeline(note=_note(), transcript="t")
    client, tracker, _ = setup(pipeline=pipeline)
    pipeline.note_error = NoteParsingError("bad json")

    client.post("/api/soap/regenerate", json={"transcript": "t"})

    props = tracker.only("note_regenerated")["properties"]
    assert props["outcome"] == "failed"
    assert props["error_type"] == "NoteParsingError"


def test_note_saved_reports_which_boxes_changed_and_how_much(setup):
    client, tracker, _ = setup()
    exam = client.post("/api/soap", content=b"RIFF").json()

    client.put(f"/api/exams/{exam['id']}", json=_saved_body(exam, plan="rewritten entirely"))

    props = tracker.only("note_saved")["properties"]
    assert props["exam_id"] == exam["id"]
    assert props["fields_changed"] == ["plan"]
    assert props["plan_similarity"] < 1.0
    assert props["subjective_similarity"] == 1.0
    assert props["includes_regenerated_content"] is False


def test_note_saved_flags_a_save_that_follows_a_regenerate(setup):
    client, tracker, _ = setup()
    exam = client.post("/api/soap", content=b"RIFF").json()

    client.post("/api/soap/regenerate", json={"transcript": "t", "exam_id": exam["id"]})
    client.put(f"/api/exams/{exam['id']}", json=_saved_body(exam, plan="regenerated plan"))
    client.put(f"/api/exams/{exam['id']}", json=_saved_body(exam, plan="hand edit"))

    flags = [e["properties"]["includes_regenerated_content"] for e in tracker.named("note_saved")]
    assert flags == [True, False]


def test_no_note_saved_event_for_an_unknown_exam(setup):
    client, tracker, _ = setup()

    client.put("/api/exams/nope", json=_saved_body({f: "" for f in (
        "subjective", "objective", "assessment", "plan", "transcript")}))

    assert tracker.named("note_saved") == []


def test_exam_deleted_is_reported(setup):
    client, tracker, _ = setup()
    exam_id = client.post("/api/soap", content=b"RIFF").json()["id"]

    client.delete(f"/api/exams/{exam_id}")
    client.delete(f"/api/exams/{exam_id}")

    assert tracker.only("exam_deleted")["properties"]["exam_id"] == exam_id


# --- Q4: injecting the same note from the phone ---------------------------


def test_injection_requested_counts_attempts_per_exam_and_prior_edits(setup):
    client, tracker, _ = setup()
    exam = client.post("/api/soap", content=b"RIFF").json()

    client.post(f"/api/exams/{exam['id']}/inject", headers=CLIENT_HEADERS)
    client.put(f"/api/exams/{exam['id']}", json=_saved_body(exam, plan="edited"))
    client.post(f"/api/exams/{exam['id']}/inject", headers=CLIENT_HEADERS)

    events = tracker.named("injection_requested")
    assert [e["properties"]["attempt_number"] for e in events] == [1, 2]
    assert [e["properties"]["edited_before_inject"] for e in events] == [False, True]
    assert events[0]["properties"]["exam_id"] == exam["id"]
    assert events[0]["properties"]["request_id"]
    assert events[0]["distinct_id"] == "demo-vet-1"


def test_a_save_with_no_changes_does_not_count_as_an_edit(setup):
    client, tracker, _ = setup()
    exam = client.post("/api/soap", content=b"RIFF").json()

    client.put(f"/api/exams/{exam['id']}", json=_saved_body(exam))
    client.post(f"/api/exams/{exam['id']}/inject")

    assert tracker.only("injection_requested")["properties"]["edited_before_inject"] is False


# --- lifecycle + privacy ---------------------------------------------------


def test_analytics_are_flushed_on_shutdown(setup):
    client, tracker, _ = setup()
    with client:
        pass
    assert tracker.shut_down


def test_no_event_ever_carries_patient_data(setup):
    pipeline = FakePipeline(
        note=_note(SENTINEL, patient_name=SENTINEL), transcript=f"{SENTINEL} vomiting"
    )
    client, tracker, _ = setup(pipeline=pipeline)

    exam = client.post("/api/soap", content=SENTINEL.encode(), headers=CLIENT_HEADERS).json()
    client.post(
        "/api/soap/regenerate", json={"transcript": f"{SENTINEL} edited", "exam_id": exam["id"]}
    )
    client.put(
        f"/api/exams/{exam['id']}",
        json=_saved_body(exam, plan=f"{SENTINEL} new plan", patient_name=SENTINEL),
    )
    client.post(f"/api/exams/{exam['id']}/inject")
    pipeline.note_error = NoteParsingError(f"model did not return valid JSON: {SENTINEL}")
    client.post("/api/soap", content=b"RIFF")
    client.post("/api/soap/regenerate", json={"transcript": SENTINEL})
    client.delete(f"/api/exams/{exam['id']}")

    assert len(tracker.events) >= 7
    assert SENTINEL not in json.dumps(tracker.events)


def test_no_appointment_event_ever_carries_patient_data(setup):
    named = _note(SENTINEL, patient_name=SENTINEL)
    pipeline = FakePipeline(notes=[named, named], transcript=f"{SENTINEL} two dogs")
    client, tracker, _ = setup(pipeline=pipeline)

    appointment = client.post("/api/appointments", content=SENTINEL.encode()).json()
    client.post(
        "/api/appointments/regenerate",
        json={"transcript": f"{SENTINEL} edited", "appointment_id": appointment["id"]},
    )
    exams = [
        {**e, "plan": f"{SENTINEL} plan", "patient_name": SENTINEL} for e in appointment["exams"]
    ]
    client.put(
        f"/api/appointments/{appointment['id']}",
        json={"transcript": f"{SENTINEL} fixed", "exams": exams[:1] + [{**exams[1], "id": None}]},
    )
    pipeline.note_error = NoteParsingError(f"model did not return valid JSON: {SENTINEL}")
    pending = client.post("/api/appointments", content=b"RIFF").json()
    client.post(f"/api/appointments/{pending['id']}/notes")
    client.post("/api/appointments/regenerate", json={"transcript": SENTINEL})
    client.delete(f"/api/appointments/{appointment['id']}")

    assert len(tracker.events) >= 7
    assert SENTINEL not in json.dumps(tracker.events)


def test_async_upload_reports_soap_generated_from_the_worker(setup):
    named = _note("x", patient_name="Bella")
    client, tracker, _ = setup(pipeline=FakePipeline(notes=[named, named], transcript="two dogs"))
    with client:
        appointment = client.post(
            "/api/appointments",
            content=b"m4a",
            headers={**CLIENT_HEADERS, "Prefer": "respond-async", "X-Audio-Duration-Ms": "4000"},
        ).json()
        client.portal.call(client.app.state.worker.drain)

    [event] = [e for e in tracker.events if e["event"] == "soap_generated"]
    assert event["distinct_id"] == "demo-vet-1"
    props = event["properties"]
    assert props["mode"] == "async"
    assert props["outcome"] == "complete"
    assert props["appointment_id"] == appointment["id"]
    assert props["patient_count"] == 2
    assert props["source_app"] == "mobile"
    assert props["audio_duration_ms"] == 4000
    assert {"transcribe_ms", "note_gen_ms"} <= props.keys()


def test_no_async_upload_event_ever_carries_patient_data(setup):
    named = _note(SENTINEL, patient_name=SENTINEL)
    pipeline = FakePipeline(notes=[named], transcript=f"{SENTINEL} vomiting")
    client, tracker, _ = setup(pipeline=pipeline)
    headers = {**CLIENT_HEADERS, "Prefer": "respond-async"}
    with client:
        client.post("/api/appointments", content=SENTINEL.encode(), headers=headers)
        client.portal.call(client.app.state.worker.drain)
        pipeline.note_error = NoteParsingError(f"model did not return valid JSON: {SENTINEL}")
        client.post("/api/appointments", content=b"other", headers=headers)
        client.portal.call(client.app.state.worker.drain)

    assert len([e for e in tracker.events if e["event"] == "soap_generated"]) == 2
    assert SENTINEL not in json.dumps(tracker.events)


def test_create_app_without_analytics_still_serves_requests(make_config):
    # No analytics passed and no key configured -> the no-op tracker.
    client = TestClient(
        create_app(config=make_config(), pipeline=FakePipeline(note=_note(), transcript="t"))
    )
    assert client.post("/api/soap", content=b"RIFF").status_code == 200
