import json

import pytest

from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import (
    ExamEdit,
    ExamStore,
    JsonFileExamStore,
    UnknownExamError,
)


def _note(a="a", patient_name=None):
    return SoapNote(subjective="s", objective="o", assessment=a, plan="p", patient_name=patient_name)


BELLA = SoapNote("s1", "o1", "a1", "p1", patient_name="Bella")
MAX = SoapNote("s2", "o2", "a2", "p2", patient_name="Max")
EMPTY = SoapNote("", "", "", "")


def _fixed_store():
    ids = iter(f"id-{n}" for n in range(1, 100))
    times = iter(f"2026-01-{n:02d}T00:00:00Z" for n in range(1, 100))
    return ExamStore(id_factory=lambda: next(ids), clock=lambda: next(times))


# --- single-animal exams (add/get/list/update/delete) --------------------------


def test_add_persists_an_exam_with_generated_id_and_timestamp():
    store = _fixed_store()

    exam = store.add(_note(), transcript="owner reports vomiting", patient_name="Rex")

    assert exam.id == "id-2"
    assert exam.appointment_id == "id-1"
    # Animals recorded together share the appointment's timestamp.
    assert exam.created_at == "2026-01-01T00:00:00Z"
    assert exam.to_dict() == {
        "id": "id-2",
        "appointment_id": "id-1",
        "created_at": "2026-01-01T00:00:00Z",
        "patient_name": "Rex",
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "p",
        "transcript": "owner reports vomiting",
        "note_pending": False,
    }


def test_get_returns_the_stored_exam_and_none_when_missing():
    store = _fixed_store()
    exam = store.add(_note(), transcript="t")

    assert store.get(exam.id) == exam
    assert store.get("nope") is None


def test_list_returns_exams_newest_appointment_first_animals_in_order():
    store = _fixed_store()
    first = store.add(_note("first"), transcript="t1")
    two = store.add_appointment("t2", [BELLA, MAX])

    listed = store.list()

    assert [e.id for e in listed] == [two.exams[0].id, two.exams[1].id, first.id]


def test_update_replaces_note_fields_and_keeps_id_and_created_at():
    store = _fixed_store()
    exam = store.add(_note(), transcript="original")

    updated = store.update(
        exam.id, subjective="s2", objective="o2", assessment="a2", plan="p2",
        transcript="corrected",
    )

    assert updated.id == exam.id
    assert updated.created_at == exam.created_at
    assert updated.assessment == "a2"
    assert updated.transcript == "corrected"
    assert store.get(exam.id).transcript == "corrected"


def test_update_without_a_transcript_keeps_the_shared_one():
    store = _fixed_store()
    exam = store.add(_note(), transcript="original")

    updated = store.update(exam.id, subjective="s", objective="o", assessment="a", plan="p")

    assert updated.transcript == "original"


def test_update_returns_none_for_an_unknown_id():
    store = _fixed_store()

    assert store.update("missing", subjective="", objective="", assessment="", plan="") is None


def test_delete_removes_the_exam_and_reports_whether_it_existed():
    store = _fixed_store()
    exam = store.add(_note(), transcript="t")

    assert store.delete(exam.id) is True
    assert store.get(exam.id) is None
    assert store.delete(exam.id) is False


def test_add_can_mark_an_exam_as_note_pending():
    store = _fixed_store()

    exam = store.add(_note(), transcript="t", note_pending=True)

    assert exam.note_pending is True
    assert store.add(_note(), transcript="t2").note_pending is False


def test_update_clears_note_pending_when_the_note_is_filled_in():
    store = _fixed_store()
    pending = store.add(_note(), transcript="t", note_pending=True)

    updated = store.update(pending.id, subjective="s", objective="o", assessment="a", plan="p")

    assert updated.note_pending is False


# --- appointments: one shared transcript, one exam per animal -------------------


def test_add_appointment_creates_one_exam_per_note_sharing_the_transcript():
    store = _fixed_store()

    appointment = store.add_appointment("two dogs today", [BELLA, MAX])

    assert appointment.id == "id-1"
    assert appointment.transcript == "two dogs today"
    assert appointment.note_pending is False
    assert [(e.patient_name, e.plan, e.appointment_id) for e in appointment.exams] == [
        ("Bella", "p1", "id-1"),
        ("Max", "p2", "id-1"),
    ]
    assert all(e.transcript == "two dogs today" for e in appointment.exams)


def test_appointment_to_dict_holds_the_transcript_once():
    store = _fixed_store()

    data = store.add_appointment("two dogs today", [BELLA, MAX]).to_dict()

    assert data["id"] == "id-1"
    assert data["created_at"] == "2026-01-01T00:00:00Z"
    assert data["transcript"] == "two dogs today"
    assert data["note_pending"] is False
    assert [e["patient_name"] for e in data["exams"]] == ["Bella", "Max"]
    assert all("transcript" not in e for e in data["exams"])
    assert all(e["appointment_id"] == "id-1" for e in data["exams"])


def test_add_pending_appointment_holds_one_placeholder_exam():
    store = _fixed_store()

    appointment = store.add_pending_appointment("owner reports vomiting")

    assert appointment.note_pending is True
    [placeholder] = appointment.exams
    assert placeholder.note_pending is True
    assert placeholder.subjective == ""
    assert placeholder.transcript == "owner reports vomiting"


def test_get_appointment_and_list_appointments_newest_first():
    store = _fixed_store()
    first = store.add_appointment("t1", [BELLA])
    second = store.add_appointment("t2", [MAX])

    assert store.get_appointment(first.id) == first
    assert store.get_appointment("nope") is None
    assert [a.id for a in store.list_appointments()] == [second.id, first.id]


def test_updating_one_exams_transcript_updates_it_for_every_animal():
    store = _fixed_store()
    appointment = store.add_appointment("two dogs", [BELLA, MAX])
    bella, max_ = appointment.exams

    store.update(
        bella.id, subjective="s", objective="o", assessment="a", plan="p", transcript="corrected"
    )

    assert store.get(max_.id).transcript == "corrected"
    assert store.get_appointment(appointment.id).transcript == "corrected"


def test_deleting_one_animal_keeps_the_rest_of_the_appointment():
    store = _fixed_store()
    appointment = store.add_appointment("two dogs", [BELLA, MAX])
    bella, max_ = appointment.exams

    assert store.delete(bella.id) is True

    assert [e.id for e in store.get_appointment(appointment.id).exams] == [max_.id]


def test_deleting_the_last_animal_deletes_the_appointment():
    store = _fixed_store()
    exam = store.add(_note(), transcript="t")

    store.delete(exam.id)

    assert store.get_appointment(exam.appointment_id) is None
    assert store.list_appointments() == []


def test_delete_appointment_removes_every_animal():
    store = _fixed_store()
    appointment = store.add_appointment("two dogs", [BELLA, MAX])

    assert store.delete_appointment(appointment.id) is True

    assert store.get_appointment(appointment.id) is None
    assert store.list() == []
    assert store.delete_appointment(appointment.id) is False


# --- update_appointment: replace the transcript and the set of animals ----------


def _edit(exam=None, **fields):
    base = dict(subjective="s", objective="o", assessment="a", plan="p", patient_name=None)
    if exam is not None:
        base.update(
            id=exam.id, subjective=exam.subjective, objective=exam.objective,
            assessment=exam.assessment, plan=exam.plan, patient_name=exam.patient_name,
        )
    base.update(fields)
    return ExamEdit(**base)


def test_update_appointment_edits_animals_and_the_shared_transcript():
    store = _fixed_store()
    appointment = store.add_appointment("two dogs", [BELLA, MAX])
    bella, max_ = appointment.exams

    updated = store.update_appointment(
        appointment.id,
        transcript="corrected",
        exams=[_edit(bella, plan="new plan"), _edit(max_, patient_name="Maximus")],
    )

    assert updated.transcript == "corrected"
    assert [(e.id, e.patient_name, e.plan) for e in updated.exams] == [
        (bella.id, "Bella", "new plan"),
        (max_.id, "Maximus", "p2"),
    ]
    assert [e.created_at for e in updated.exams] == [bella.created_at, max_.created_at]
    assert store.get(max_.id).transcript == "corrected"


def test_update_appointment_adds_entries_without_an_id_and_removes_missing_ones():
    store = _fixed_store()
    appointment = store.add_appointment("two dogs", [BELLA, MAX])
    bella, max_ = appointment.exams

    updated = store.update_appointment(
        appointment.id,
        transcript="two dogs",
        exams=[_edit(bella), _edit(patient_name="Luna", plan="added")],
    )

    assert [e.patient_name for e in updated.exams] == ["Bella", "Luna"]
    luna = updated.exams[1]
    assert luna.id not in (bella.id, max_.id)
    assert luna.appointment_id == appointment.id
    assert luna.note_pending is False
    assert store.get(max_.id) is None
    assert store.get(luna.id).plan == "added"


def test_update_appointment_clears_note_pending():
    store = _fixed_store()
    appointment = store.add_pending_appointment("t")
    [placeholder] = appointment.exams

    updated = store.update_appointment(
        appointment.id, transcript="t", exams=[_edit(placeholder, plan="by hand")]
    )

    assert updated.note_pending is False


def test_update_appointment_returns_none_for_an_unknown_appointment():
    assert _fixed_store().update_appointment("nope", transcript="t", exams=[_edit()]) is None


def test_update_appointment_rejects_an_exam_from_another_appointment_and_changes_nothing():
    store = _fixed_store()
    one = store.add_appointment("one", [BELLA])
    other = store.add_appointment("other", [MAX])

    with pytest.raises(UnknownExamError):
        store.update_appointment(
            one.id, transcript="changed", exams=[_edit(one.exams[0]), _edit(other.exams[0])]
        )

    assert store.get_appointment(one.id) == one
    assert store.get_appointment(other.id) == other


def test_update_appointment_rejects_the_same_exam_twice():
    store = _fixed_store()
    appointment = store.add_appointment("t", [BELLA])
    [bella] = appointment.exams

    with pytest.raises(ValueError):
        store.update_appointment(appointment.id, transcript="t", exams=[_edit(bella), _edit(bella)])

    assert store.get_appointment(appointment.id) == appointment


def test_update_appointment_rejects_an_empty_list_of_animals():
    store = _fixed_store()
    appointment = store.add_appointment("t", [BELLA])

    with pytest.raises(ValueError):
        store.update_appointment(appointment.id, transcript="t", exams=[])


# --- complete_pending -------------------------------------------------------------


def test_complete_pending_fills_in_a_pending_exam_and_clears_the_flag():
    store = _fixed_store()
    pending = store.add(EMPTY, transcript="t", note_pending=True)

    exam = store.complete_pending(pending.id, [_note(a="generated")])

    assert exam.assessment == "generated"
    assert exam.note_pending is False
    assert exam.transcript == "t"
    assert exam.created_at == pending.created_at
    assert store.get(pending.id).assessment == "generated"


def test_complete_pending_leaves_an_already_completed_exam_untouched():
    # A vet who filled the note in by hand must never have it overwritten by a
    # late "finish this note" retry.
    store = _fixed_store()
    pending = store.add(EMPTY, transcript="t", note_pending=True)
    store.update(pending.id, subjective="vet s", objective="vet o", assessment="vet a", plan="vet p")

    exam = store.complete_pending(pending.id, [_note(a="generated")])

    assert exam.assessment == "vet a"
    assert store.get(pending.id).assessment == "vet a"


def test_complete_pending_returns_none_for_an_unknown_id():
    assert _fixed_store().complete_pending("missing", [_note()]) is None


def test_complete_pending_adds_each_further_patient_to_the_same_appointment():
    store = _fixed_store()
    appointment = store.add_pending_appointment("two dogs")
    [placeholder] = appointment.exams

    exam = store.complete_pending(placeholder.id, [BELLA, MAX])

    assert exam.id == placeholder.id
    assert exam.patient_name == "Bella"
    completed = store.get_appointment(appointment.id)
    assert completed.note_pending is False
    assert [(e.patient_name, e.transcript, e.note_pending) for e in completed.exams] == [
        ("Bella", "two dogs", False),
        ("Max", "two dogs", False),
    ]


def test_complete_pending_adds_no_further_patients_to_an_already_completed_exam():
    store = _fixed_store()
    pending = store.add(EMPTY, transcript="two dogs", note_pending=True)

    store.complete_pending(pending.id, [BELLA, MAX])
    store.complete_pending(pending.id, [BELLA, MAX])

    assert len(store.list()) == 2


# --- returned records are snapshots ------------------------------------------------


def test_returned_records_do_not_change_under_later_writes():
    # Handlers read records outside the store's lock; a later write must never
    # mutate one they're still holding.
    store = _fixed_store()
    appointment = store.add_appointment("t", [BELLA, MAX])

    store.update(appointment.exams[0].id, subjective="x", objective="x", assessment="x",
                 plan="x", transcript="changed")

    assert appointment.transcript == "t"
    assert appointment.exams[0].plan == "p1"


# --- JSON file store -----------------------------------------------------------------


def test_json_file_store_round_trips_appointments_across_instances(tmp_path):
    path = tmp_path / "exams.json"
    store = JsonFileExamStore(path)
    appointment = store.add_appointment("two dogs", [BELLA, MAX])
    pending = store.add_pending_appointment("pending one")

    reopened = JsonFileExamStore(path)

    assert reopened.get_appointment(appointment.id) == appointment
    assert reopened.get_appointment(pending.id) == pending
    assert [a.id for a in reopened.list_appointments()] == [pending.id, appointment.id]


def test_json_file_store_writes_each_transcript_once(tmp_path):
    path = tmp_path / "exams.json"
    JsonFileExamStore(path).add_appointment("two dogs", [BELLA, MAX])

    data = json.loads(path.read_text())

    [appointment] = data["appointments"]
    assert appointment["transcript"] == "two dogs"
    assert all("transcript" not in e for e in appointment["exams"])


def test_json_file_store_persists_every_kind_of_write(tmp_path):
    path = tmp_path / "exams.json"
    store = JsonFileExamStore(path)
    keep = store.add_appointment("keep", [BELLA, MAX])
    drop = store.add_appointment("drop", [BELLA])
    pending = store.add_pending_appointment("pending")

    store.update(keep.exams[0].id, subjective="s", objective="o", assessment="a", plan="edited",
                 transcript="keep corrected")
    store.delete(keep.exams[1].id)
    store.delete_appointment(drop.id)
    store.complete_pending(pending.exams[0].id, [BELLA, MAX])
    store.update_appointment(pending.id, transcript="pending", exams=[
        _edit(e) for e in store.get_appointment(pending.id).exams
    ] + [_edit(patient_name="Luna")])

    reopened = JsonFileExamStore(path)
    assert reopened.list_appointments() == store.list_appointments()


def test_json_file_store_loads_a_flat_list_of_exams_as_one_appointment_each(tmp_path):
    # The file written before appointments existed: one exam per entry, each
    # with its own transcript. Loading it must not crash the backend.
    path = tmp_path / "exams.json"
    path.write_text(json.dumps([{
        "id": "old-1", "created_at": "2025-01-01T00:00:00Z", "subjective": "s",
        "objective": "o", "assessment": "a", "plan": "p", "transcript": "old transcript",
        "patient_name": "Rex", "note_pending": False,
    }]))

    store = JsonFileExamStore(path)

    exam = store.get("old-1")
    assert exam.transcript == "old transcript"
    assert exam.patient_name == "Rex"
    assert store.get_appointment(exam.appointment_id).exams == (exam,)


# --- async (processing) appointments -------------------------------------------


def test_create_processing_saves_a_processing_appointment_with_its_key():
    store = _fixed_store()

    appointment, created = store.create_processing("key-1", "sha-1", "audio/mp4")

    assert created is True
    assert appointment.stage == "processing"
    assert appointment.recording_key == "key-1"
    assert appointment.audio_sha256 == "sha-1"
    assert appointment.audio_mime == "audio/mp4"
    assert appointment.to_dict()["status"] == "processing"
    assert store.get_appointment(appointment.id) == appointment


def test_create_processing_with_a_known_key_returns_the_existing_appointment():
    store = _fixed_store()
    first, _ = store.create_processing("key-1", "sha-1", "audio/mp4")

    again, created = store.create_processing("key-1", "sha-other", "audio/mp4")

    assert created is False
    assert again == first
    assert len(store.list_appointments()) == 1


def test_create_processing_without_a_key_always_creates():
    store = _fixed_store()
    store.create_processing(None, "sha-1", "audio/mp4")
    store.create_processing(None, "sha-1", "audio/mp4")
    assert len(store.list_appointments()) == 2


def test_the_key_still_finds_the_appointment_once_processing_is_done():
    store = _fixed_store()
    appointment, _ = store.create_processing("key-1", "sha-1", "audio/mp4")
    store.finish_processing(appointment.id, "two dogs", [BELLA, MAX])

    again, created = store.create_processing("key-1", "sha-1", "audio/mp4")

    assert created is False
    assert again.id == appointment.id
    assert again.to_dict()["status"] == "complete"


def test_finish_processing_fills_in_the_transcript_and_one_exam_per_animal():
    store = _fixed_store()
    appointment, _ = store.create_processing("key-1", "sha-1", "audio/mp4")

    done = store.finish_processing(appointment.id, "two dogs", [BELLA, MAX])

    assert done.stage is None
    assert done.transcript == "two dogs"
    assert [e.patient_name for e in done.exams] == ["Bella", "Max"]
    assert all(e.transcript == "two dogs" and not e.note_pending for e in done.exams)
    assert done.to_dict()["status"] == "complete"


def test_finish_processing_of_a_deleted_appointment_returns_none():
    store = _fixed_store()
    appointment, _ = store.create_processing("key-1", "sha-1", "audio/mp4")
    store.delete_appointment(appointment.id)
    assert store.finish_processing(appointment.id, "t", [BELLA]) is None
    assert store.list_appointments() == []


def test_mark_note_pending_keeps_the_transcript_for_a_later_note():
    store = _fixed_store()
    appointment, _ = store.create_processing("key-1", "sha-1", "audio/mp4")

    pending = store.mark_note_pending(appointment.id, "two dogs")

    assert pending.stage is None
    assert pending.transcript == "two dogs"
    assert pending.to_dict()["status"] == "note_pending"
    # The existing /notes path finishes it.
    store.complete_pending(pending.exams[0].id, [BELLA])
    assert store.get_appointment(appointment.id).to_dict()["status"] == "complete"


@pytest.mark.parametrize("stage", ["failed", "no_speech"])
def test_mark_failed_sets_a_terminal_status(stage):
    store = _fixed_store()
    appointment, _ = store.create_processing("key-1", "sha-1", "audio/mp4")

    failed = store.mark_failed(appointment.id, stage)

    assert failed.stage == stage
    assert failed.to_dict()["status"] == stage


def test_restart_processing_puts_a_failed_appointment_back_to_processing():
    store = _fixed_store()
    appointment, _ = store.create_processing("key-1", "sha-1", "audio/mp4")
    store.mark_failed(appointment.id, "failed")

    again = store.restart_processing(appointment.id)

    assert again.stage == "processing"
    assert store.restart_processing("missing") is None


def test_list_processing_returns_only_appointments_still_processing():
    store = _fixed_store()
    waiting, _ = store.create_processing("k1", "s1", "audio/mp4")
    done, _ = store.create_processing("k2", "s2", "audio/mp4")
    store.finish_processing(done.id, "t", [BELLA])
    store.add_appointment("sync", [MAX])

    assert [a.id for a in store.list_processing()] == [waiting.id]


def test_desktop_list_hides_appointments_without_a_transcript_yet():
    store = _fixed_store()
    store.create_processing("k1", "s1", "audio/mp4")
    failed, _ = store.create_processing("k2", "s2", "audio/mp4")
    store.mark_failed(failed.id, "failed")
    synced = store.add_appointment("sync", [MAX])

    assert [e.id for e in store.list()] == [synced.exams[0].id]


def test_existing_appointments_report_complete_or_note_pending():
    store = _fixed_store()
    assert store.add_appointment("t", [BELLA]).to_dict()["status"] == "complete"
    assert store.add_pending_appointment("t").to_dict()["status"] == "note_pending"


def test_json_file_store_round_trips_processing_fields(tmp_path):
    path = tmp_path / "exams.json"
    store = JsonFileExamStore(path)
    processing, _ = store.create_processing("key-1", "sha-1", "audio/mp4")
    failed, _ = store.create_processing("key-2", "sha-2", "audio/wav")
    store.mark_failed(failed.id, "failed")

    reopened = JsonFileExamStore(path)

    assert reopened.list_appointments() == store.list_appointments()
    assert [a.id for a in reopened.list_processing()] == [processing.id]
    assert reopened.create_processing("key-2", "sha-2", "audio/wav") == (
        reopened.get_appointment(failed.id),
        False,
    )


def test_json_file_store_loads_appointments_saved_before_processing_existed(tmp_path):
    path = tmp_path / "exams.json"
    path.write_text(json.dumps({"appointments": [{
        "id": "a1", "created_at": "2026-01-01T00:00:00Z", "transcript": "t",
        "exams": [{"id": "e1", "created_at": "2026-01-01T00:00:00Z", "subjective": "s",
                   "objective": "o", "assessment": "a", "plan": "p",
                   "patient_name": None, "note_pending": False}],
    }]}))

    appointment = JsonFileExamStore(path).get_appointment("a1")

    assert appointment.stage is None
    assert appointment.recording_key is None
    assert appointment.to_dict()["status"] == "complete"


def test_a_note_written_by_hand_for_a_failed_recording_makes_it_a_normal_appointment():
    store = _fixed_store()
    appointment, _ = store.create_processing("k", "sha", "audio/mp4")
    store.mark_failed(appointment.id, "failed")

    updated = store.update_appointment(appointment.id, transcript="typed up", exams=[
        ExamEdit("s", "o", "a", "p", patient_name="Bella", id=appointment.exams[0].id)
    ])

    assert updated.stage is None
    assert updated.to_dict()["status"] == "complete"
