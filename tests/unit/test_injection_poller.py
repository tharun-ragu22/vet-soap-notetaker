import pytest

from vet_soap_notetaker.api_client import ApiClientError
from vet_soap_notetaker.injection_poller import InjectionPoller


class FakeApiClient:
    def __init__(self, pending, fetch_error=None, ack_error=None):
        # `pending` is a list of poll results (one per process_once call); a
        # single list is reused for every poll.
        self._pending = pending
        self.fetch_error = fetch_error
        self.ack_error = ack_error
        self.fetch_calls = 0
        self.acked = []

    def fetch_pending_injections(self):
        self.fetch_calls += 1
        if self.fetch_error is not None:
            raise self.fetch_error
        if self._pending and isinstance(self._pending[0], list):
            # A queue of per-poll results.
            return self._pending.pop(0)
        return list(self._pending)

    def ack_injection(self, request_id, outcome):
        if self.ack_error is not None:
            raise self.ack_error
        self.acked.append((request_id, outcome))


def _req(req_id, exam_id="exam-1"):
    return {"id": req_id, "exam_id": exam_id, "exam": {"assessment": "a"}}


def test_process_once_dispatches_each_request_and_acks_it():
    dispatched = []
    api = FakeApiClient(pending=[_req("req-1"), _req("req-2")])
    poller = InjectionPoller(api_client=api, on_injection=dispatched.append)

    handled = poller.process_once()

    assert [r["id"] for r in dispatched] == ["req-1", "req-2"]
    assert [rid for rid, _ in api.acked] == ["req-1", "req-2"]
    assert handled == ["req-1", "req-2"]


def test_process_once_returns_empty_and_skips_dispatch_when_fetch_fails():
    dispatched = []
    api = FakeApiClient(pending=[], fetch_error=ApiClientError("backend down"))
    poller = InjectionPoller(api_client=api, on_injection=dispatched.append)

    assert poller.process_once() == []
    assert dispatched == []


def test_same_request_is_never_dispatched_twice():
    dispatched = []
    # Backend keeps returning the same request across polls (e.g. ack was lost).
    api = FakeApiClient(pending=[_req("req-1")])
    poller = InjectionPoller(api_client=api, on_injection=dispatched.append)

    poller.process_once()
    poller.process_once()

    assert [r["id"] for r in dispatched] == ["req-1"]


def test_ack_failure_still_prevents_redispatch():
    dispatched = []
    api = FakeApiClient(pending=[_req("req-1")], ack_error=ApiClientError("ack failed"))
    poller = InjectionPoller(api_client=api, on_injection=dispatched.append)

    poller.process_once()  # dispatch succeeds, ack raises (swallowed)
    poller.process_once()  # must not dispatch again

    assert [r["id"] for r in dispatched] == ["req-1"]


def test_dispatch_failure_is_not_acked_and_retries_next_poll():
    calls = []

    def flaky(req):
        calls.append(req["id"])
        if len(calls) == 1:
            raise RuntimeError("main thread busy")

    api = FakeApiClient(pending=[_req("req-1")])
    poller = InjectionPoller(api_client=api, on_injection=flaky)

    poller.process_once()  # dispatch raises -> not acked, not marked handled
    assert api.acked == []

    poller.process_once()  # retried
    assert calls == ["req-1", "req-1"]
    assert [rid for rid, _ in api.acked] == ["req-1"]


def test_one_bad_request_does_not_block_the_others():
    dispatched = []

    def flaky(req):
        if req["id"] == "req-1":
            raise RuntimeError("boom")
        dispatched.append(req["id"])

    api = FakeApiClient(pending=[_req("req-1"), _req("req-2")])
    poller = InjectionPoller(api_client=api, on_injection=flaky)

    poller.process_once()

    assert dispatched == ["req-2"]
    assert [rid for rid, _ in api.acked] == ["req-2"]
