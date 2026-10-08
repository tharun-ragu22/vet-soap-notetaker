import httpx
import pytest

from vet_soap_notetaker_backend.llm import http_retry
from vet_soap_notetaker_backend.llm.http_retry import post_with_retries

URL = "https://example.test/endpoint"


def _response(status: int) -> httpx.Response:
    # raise_for_status() needs a request attached, so give every canned response one.
    return httpx.Response(status, json={"ok": status}, request=httpx.Request("POST", URL))


class _FakePost:
    """Stands in for httpx.post, yielding a scripted sequence of outcomes.

    Each outcome is either an httpx.Response to return or an Exception to raise.
    Once the script is exhausted it repeats the last outcome, so "always fails"
    just needs a single trailing failure.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_kwargs = None

    def __call__(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def sleeps(monkeypatch):
    """Capture backoff sleeps instead of actually sleeping."""
    recorded = []
    monkeypatch.setattr(http_retry.time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


def _install(monkeypatch, outcomes):
    fake = _FakePost(outcomes)
    monkeypatch.setattr(http_retry.httpx, "post", fake)
    return fake


def test_returns_immediately_on_success(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(200)])

    response = post_with_retries(url=URL)

    assert response.status_code == 200
    assert fake.calls == 1
    assert sleeps == []


def test_retries_on_5xx_then_succeeds(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(503), _response(200)])

    response = post_with_retries(url=URL)

    assert response.status_code == 200
    assert fake.calls == 2
    assert sleeps == [1.0]


def test_retries_on_429_then_succeeds(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(429), _response(200)])

    response = post_with_retries(url=URL)

    assert response.status_code == 200
    assert fake.calls == 2


def test_retries_on_transport_error_then_succeeds(monkeypatch, sleeps):
    timeout = httpx.ConnectTimeout("timed out", request=httpx.Request("POST", URL))
    fake = _install(monkeypatch, [timeout, _response(200)])

    response = post_with_retries(url=URL)

    assert response.status_code == 200
    assert fake.calls == 2
    assert sleeps == [1.0]


def test_exhausts_three_retries_then_raises(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(503)])

    with pytest.raises(httpx.HTTPStatusError):
        post_with_retries(url=URL)

    # initial attempt + 3 retries = 4 calls, with exponential backoff between them
    assert fake.calls == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_does_not_retry_on_4xx(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(403)])

    with pytest.raises(httpx.HTTPStatusError):
        post_with_retries(url=URL)

    assert fake.calls == 1
    assert sleeps == []


def test_backoff_base_is_configurable(monkeypatch, sleeps):
    _install(monkeypatch, [_response(503)])

    with pytest.raises(httpx.HTTPStatusError):
        post_with_retries(url=URL, backoff_base_seconds=0.5)

    assert sleeps == [0.5, 1.0, 2.0]


def test_max_retries_is_configurable(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(503)])

    with pytest.raises(httpx.HTTPStatusError):
        post_with_retries(url=URL, max_retries=1)

    assert fake.calls == 2
    assert sleeps == [1.0]


def test_passes_through_post_kwargs(monkeypatch, sleeps):
    fake = _install(monkeypatch, [_response(200)])

    post_with_retries(url=URL, params={"key": "secret"}, json={"a": 1}, timeout=120)

    assert fake.last_kwargs["params"] == {"key": "secret"}
    assert fake.last_kwargs["json"] == {"a": 1}
    assert fake.last_kwargs["timeout"] == 120
