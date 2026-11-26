import json

import pytest

from vet_soap_notetaker.api_client import (
    ApiClientError,
    Appointment,
    BackendUnreachableError,
    Exam,
    ExamDraft,
)
from vet_soap_notetaker.appointment_store import IAppointmentStore
from vet_soap_notetaker.backend_history_store import BackendHistoryStore, get_cache_path


def _exam(exam_id="exam-1", plan="p", patient_name=None, appointment_id="appt-1"):
    return Exam(
        id=exam_id,
        created_at="2026-11-23T09:00:00+00:00",
        subjective="s",
        objective="o",
        assessment="a",
        plan=plan,
        transcript="t",
        patient_name=patient_name,
        appointment_id=appointment_id,
    )


def _appointment(appointment_id="appt-1", exams=None, status="complete", transcript="t"):
    return Appointment(
        id=appointment_id,
        created_at="2026-11-23T09:00:00+00:00",
        transcript=transcript,
        status=status,
        exams=exams if exams is not None else [_exam(appointment_id=appointment_id)],
    )


class FakeApiClient:
    def __init__(self, appointments=None):
        self._appointments = list(appointments or [])
        self.fail_with = None
        self.saved = []
        self.deleted = []

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    def list_appointments(self):
        self._maybe_fail()
        return list(self._appointments)

    def save_appointment(self, appointment_id, *, transcript, exams):
        self._maybe_fail()
        self.saved.append((appointment_id, transcript, list(exams)))
        saved = _appointment(
            appointment_id,
            exams=[
                _exam(e.id or f"new-{i}", plan=e.plan, patient_name=e.patient_name,
                      appointment_id=appointment_id)
                for i, e in enumerate(exams)
            ],
            transcript=transcript,
        )
        self._appointments = [saved if a.id == appointment_id else a for a in self._appointments]
        return saved

    def delete_appointment(self, appointment_id):
        self._maybe_fail()
        self.deleted.append(appointment_id)
        self._appointments = [a for a in self._appointments if a.id != appointment_id]

    def retry_appointment(self, appointment_id):
        self._maybe_fail()
        return _appointment(appointment_id, exams=[], status="processing")

    def complete_appointment_notes(self, appointment_id):
        self._maybe_fail()
        return _appointment(appointment_id)


def _store(tmp_path, api):
    return BackendHistoryStore(api, cache_path=tmp_path / "cache.json")


def test_it_is_an_appointment_store(tmp_path):
    assert isinstance(_store(tmp_path, FakeApiClient()), IAppointmentStore)


def test_the_cache_is_a_new_file_so_an_old_exam_cache_is_never_misread():
    assert get_cache_path().name == "appointments_cache.json"


def test_list_appointments_returns_the_backend_appointments(tmp_path):
    api = FakeApiClient([_appointment("appt-1"), _appointment("appt-2")])

    assert [a.id for a in _store(tmp_path, api).list_appointments()] == ["appt-1", "appt-2"]


def test_list_appointments_serves_the_cache_when_the_backend_is_down(tmp_path):
    two_animals = _appointment(
        "appt-1",
        exams=[_exam("e1", patient_name="Bella"), _exam("e2", patient_name="Max", plan="max")],
    )
    api = FakeApiClient([two_animals])
    store = _store(tmp_path, api)
    store.list_appointments()

    api.fail_with = BackendUnreachableError("down")
    [cached] = store.list_appointments()

    assert cached == two_animals


def test_list_appointments_with_no_cache_and_no_backend_is_empty(tmp_path):
    api = FakeApiClient()
    api.fail_with = ApiClientError("down")

    assert _store(tmp_path, api).list_appointments() == []


def test_an_unreadable_cache_is_treated_as_empty(tmp_path):
    (tmp_path / "cache.json").write_text("{not json")
    api = FakeApiClient()
    api.fail_with = ApiClientError("down")

    assert _store(tmp_path, api).list_appointments() == []


def test_save_appointment_sends_the_drafts_and_updates_the_cache(tmp_path):
    api = FakeApiClient([_appointment("appt-1")])
    store = _store(tmp_path, api)
    store.list_appointments()
    drafts = [ExamDraft("exam-1", "Bella", "s", "o", "a", "new plan")]

    saved = store.save_appointment("appt-1", transcript="edited", exams=drafts)

    assert api.saved == [("appt-1", "edited", drafts)]
    assert saved.exams[0].plan == "new plan"
    api.fail_with = BackendUnreachableError("down")
    assert store.list_appointments()[0].exams[0].plan == "new plan"


def test_save_appointment_returns_none_when_the_backend_is_unreachable(tmp_path):
    api = FakeApiClient([_appointment("appt-1")])
    api.fail_with = BackendUnreachableError("down")

    assert _store(tmp_path, api).save_appointment("appt-1", transcript="t", exams=[]) is None


def test_save_appointment_raises_when_the_backend_refuses_it(tmp_path):
    # An answer that says no (e.g. still processing) isn't an outage: the vet
    # must be told, not shown a silent local save.
    api = FakeApiClient([_appointment("appt-1")])
    api.fail_with = ApiClientError("backend returned 409")

    with pytest.raises(ApiClientError):
        _store(tmp_path, api).save_appointment("appt-1", transcript="t", exams=[])


def test_delete_appointment_removes_it_from_the_backend_and_the_cache(tmp_path):
    api = FakeApiClient([_appointment("appt-1"), _appointment("appt-2")])
    store = _store(tmp_path, api)
    store.list_appointments()

    assert store.delete_appointment("appt-1") is True

    assert api.deleted == ["appt-1"]
    api.fail_with = BackendUnreachableError("down")
    assert [a.id for a in store.list_appointments()] == ["appt-2"]


def test_delete_appointment_reports_failure(tmp_path):
    api = FakeApiClient([_appointment("appt-1")])
    api.fail_with = ApiClientError("down")

    assert _store(tmp_path, api).delete_appointment("appt-1") is False


def test_retry_and_complete_notes_return_the_updated_appointment(tmp_path):
    store = _store(tmp_path, FakeApiClient())

    assert store.retry("appt-1").status == "processing"
    assert store.complete_notes("appt-1").status == "complete"


def test_retry_and_complete_notes_raise_so_the_window_can_say_why(tmp_path):
    api = FakeApiClient()
    api.fail_with = ApiClientError("backend returned 502")
    store = _store(tmp_path, api)

    with pytest.raises(ApiClientError):
        store.retry("appt-1")
    with pytest.raises(ApiClientError):
        store.complete_notes("appt-1")


def test_the_cache_never_holds_more_than_the_backend_sent(tmp_path):
    api = FakeApiClient([_appointment("appt-1")])
    store = _store(tmp_path, api)

    store.list_appointments()

    cached = json.loads((tmp_path / "cache.json").read_text())
    assert [a["id"] for a in cached] == ["appt-1"]
