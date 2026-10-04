import itertools

import pytest

from vet_soap_notetaker_backend.injection_queue import InjectionQueue


@pytest.fixture
def queue():
    ids = (f"req-{n}" for n in itertools.count(1))
    clocks = (f"2026-09-22T00:00:0{n}+00:00" for n in itertools.count(0))
    return InjectionQueue(id_factory=lambda: next(ids), clock=lambda: next(clocks))


def test_request_creates_a_pending_entry(queue):
    req = queue.request("exam-1")
    assert req.id == "req-1"
    assert req.exam_id == "exam-1"
    assert req.created_at == "2026-09-22T00:00:00+00:00"
    assert req.status == "pending"
    assert req.outcome is None


def test_pending_returns_only_pending_oldest_first(queue):
    first = queue.request("exam-1")
    second = queue.request("exam-2")
    pending = queue.pending()
    assert [r.id for r in pending] == [first.id, second.id]


def test_ack_marks_request_done_with_outcome_and_removes_from_pending(queue):
    req = queue.request("exam-1")
    acked = queue.ack(req.id, outcome="injected")
    assert acked is not None
    assert acked.status == "done"
    assert acked.outcome == "injected"
    assert queue.pending() == []


def test_ack_unknown_request_returns_none(queue):
    assert queue.ack("nope", outcome="injected") is None


def test_get_returns_request_or_none(queue):
    req = queue.request("exam-1")
    assert queue.get(req.id) is req
    assert queue.get("missing") is None


def test_to_dict_shape(queue):
    req = queue.request("exam-1")
    assert req.to_dict() == {
        "id": "req-1",
        "exam_id": "exam-1",
        "created_at": "2026-09-22T00:00:00+00:00",
        "status": "pending",
        "outcome": None,
    }
