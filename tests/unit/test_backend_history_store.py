from vet_soap_notetaker.api_client import ApiClientError, Exam
from vet_soap_notetaker.backend_history_store import BackendHistoryStore


def _exam(exam_id="exam-1", assessment="a", transcript="t", patient_name=None):
    return Exam(
        id=exam_id,
        created_at="2026-09-22T00:00:01Z",
        subjective="s",
        objective="o",
        assessment=assessment,
        plan="p",
        transcript=transcript,
        patient_name=patient_name,
    )


class FakeApiClient:
    def __init__(self, history=None, fail_fetch=False):
        self._history = list(history or [])
        self.fail_fetch = fail_fetch
        self.updated = []
        self.deleted = []

    def fetch_history(self):
        if self.fail_fetch:
            raise ApiClientError("backend unreachable")
        return list(self._history)

    def update_exam(self, exam_id, *, subjective, objective, assessment, plan, transcript):
        self.updated.append(exam_id)
        updated = _exam(exam_id, assessment=assessment, transcript=transcript)
        self._history = [updated if e.id == exam_id else e for e in self._history]
        return updated

    def delete_exam(self, exam_id):
        self.deleted.append(exam_id)
        self._history = [e for e in self._history if e.id != exam_id]


def test_list_entries_returns_backend_history(tmp_path):
    api = FakeApiClient(history=[_exam("exam-1"), _exam("exam-2")])
    store = BackendHistoryStore(api, cache_path=tmp_path / "cache.json")

    entries = store.list_entries()

    assert [e.id for e in entries] == ["exam-1", "exam-2"]


def test_list_entries_writes_through_to_cache_then_serves_it_when_backend_down(tmp_path):
    api = FakeApiClient(history=[_exam("exam-1", assessment="cached")])
    cache = tmp_path / "cache.json"
    store = BackendHistoryStore(api, cache_path=cache)

    # First read hits the backend and populates the cache.
    assert [e.id for e in store.list_entries()] == ["exam-1"]
    assert cache.exists()

    # Backend goes down; the store falls back to the last-known cached copy.
    api.fail_fetch = True
    fallback = store.list_entries()
    assert [e.id for e in fallback] == ["exam-1"]
    assert fallback[0].assessment == "cached"


def test_list_entries_returns_empty_when_backend_down_and_no_cache(tmp_path):
    api = FakeApiClient(fail_fetch=True)
    store = BackendHistoryStore(api, cache_path=tmp_path / "cache.json")

    assert store.list_entries() == []


def test_update_writes_through_to_backend_and_returns_updated_exam(tmp_path):
    api = FakeApiClient(history=[_exam("exam-1", assessment="old")])
    store = BackendHistoryStore(api, cache_path=tmp_path / "cache.json")
    store.list_entries()  # prime the cache

    updated = store.update(
        "exam-1",
        subjective="s",
        objective="o",
        assessment="new",
        plan="p",
        transcript="corrected",
    )

    assert api.updated == ["exam-1"]
    assert updated.assessment == "new"
    # The cache reflects the edit so an offline read afterwards shows it.
    api.fail_fetch = True
    assert store.list_entries()[0].assessment == "new"


def test_delete_writes_through_to_backend_and_drops_from_cache(tmp_path):
    api = FakeApiClient(history=[_exam("exam-1"), _exam("exam-2")])
    store = BackendHistoryStore(api, cache_path=tmp_path / "cache.json")
    store.list_entries()  # prime the cache

    assert store.delete("exam-1") is True
    assert api.deleted == ["exam-1"]

    api.fail_fetch = True
    assert [e.id for e in store.list_entries()] == ["exam-2"]


def test_update_returns_none_when_backend_unreachable(tmp_path):
    class FailingUpdate(FakeApiClient):
        def update_exam(self, *a, **k):
            raise ApiClientError("unreachable")

    store = BackendHistoryStore(FailingUpdate(), cache_path=tmp_path / "cache.json")

    assert (
        store.update(
            "exam-1", subjective="s", objective="o", assessment="a", plan="p", transcript="t"
        )
        is None
    )


def test_delete_returns_false_when_backend_unreachable(tmp_path):
    class FailingDelete(FakeApiClient):
        def delete_exam(self, exam_id):
            raise ApiClientError("unreachable")

    store = BackendHistoryStore(FailingDelete(), cache_path=tmp_path / "cache.json")

    assert store.delete("exam-1") is False
