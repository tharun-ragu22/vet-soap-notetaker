from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import ExamStore, JsonFileExamStore


def _note(a="a"):
    return SoapNote(subjective="s", objective="o", assessment=a, plan="p")


def _fixed_store():
    ids = iter(["id-1", "id-2", "id-3"])
    times = iter(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"])
    return ExamStore(id_factory=lambda: next(ids), clock=lambda: next(times))


def test_add_persists_an_exam_with_generated_id_and_timestamp():
    store = _fixed_store()

    exam = store.add(_note(), transcript="owner reports vomiting", patient_name="Rex")

    assert exam.id == "id-1"
    assert exam.created_at == "2026-01-01T00:00:00Z"
    assert exam.patient_name == "Rex"
    assert exam.transcript == "owner reports vomiting"
    assert exam.to_dict() == {
        "id": "id-1",
        "created_at": "2026-01-01T00:00:00Z",
        "patient_name": "Rex",
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "p",
        "transcript": "owner reports vomiting",
    }


def test_get_returns_the_stored_exam_and_none_when_missing():
    store = _fixed_store()
    exam = store.add(_note(), transcript="t")

    assert store.get(exam.id) == exam
    assert store.get("nope") is None


def test_list_returns_exams_newest_first():
    store = _fixed_store()
    first = store.add(_note("first"), transcript="t1")
    second = store.add(_note("second"), transcript="t2")

    listed = store.list()

    assert [e.id for e in listed] == [second.id, first.id]


def test_update_replaces_note_fields_and_keeps_id_and_created_at():
    store = _fixed_store()
    exam = store.add(_note(), transcript="original")

    updated = store.update(
        exam.id,
        subjective="s2",
        objective="o2",
        assessment="a2",
        plan="p2",
        transcript="corrected",
    )

    assert updated is not None
    assert updated.id == exam.id
    assert updated.created_at == exam.created_at
    assert updated.assessment == "a2"
    assert updated.transcript == "corrected"
    # the change is retrievable, i.e. actually stored
    assert store.get(exam.id).transcript == "corrected"


def test_update_returns_none_for_an_unknown_id():
    store = _fixed_store()

    assert store.update("missing", subjective="", objective="", assessment="", plan="", transcript="") is None


def test_delete_removes_the_exam_and_reports_whether_it_existed():
    store = _fixed_store()
    exam = store.add(_note(), transcript="t")

    assert store.delete(exam.id) is True
    assert store.get(exam.id) is None
    # Deleting again (now unknown) reports False.
    assert store.delete(exam.id) is False


def test_json_file_store_persists_deletions_across_instances(tmp_path):
    path = tmp_path / "exams.json"
    store = JsonFileExamStore(path)
    keep = store.add(_note("keep"), transcript="k")
    drop = store.add(_note("drop"), transcript="d")

    assert store.delete(drop.id) is True

    reopened = JsonFileExamStore(path)
    assert reopened.get(drop.id) is None
    assert [e.id for e in reopened.list()] == [keep.id]


def test_json_file_store_round_trips_across_instances(tmp_path):
    path = tmp_path / "exams.json"
    store = JsonFileExamStore(path)
    exam = store.add(_note(), transcript="durable", patient_name="Bella")

    # A fresh instance reading the same file sees the persisted exam.
    reopened = JsonFileExamStore(path)
    loaded = reopened.get(exam.id)

    assert loaded is not None
    assert loaded.transcript == "durable"
    assert loaded.patient_name == "Bella"
    assert [e.id for e in reopened.list()] == [exam.id]
