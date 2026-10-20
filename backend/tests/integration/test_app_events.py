"""GET /api/events: the live stream the phone keeps open to hear when an async
upload finishes. Runs a real uvicorn server -- httpx's ASGITransport waits for
the whole response, so it can't read a stream that never ends."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from tests.integration.test_app import FakePipeline
from vet_soap_notetaker_backend.app import create_app
from vet_soap_notetaker_backend.schemas import SoapNote
from vet_soap_notetaker_backend.store import ExamStore

BELLA = SoapNote("s1", "o1", "a1", "p1", patient_name="Bella")
MAX = SoapNote("s2", "o2", "a2", "p2", patient_name="Max")


@pytest.fixture
def server(make_config, tmp_path):
    started = []

    def _start(**config):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        app = create_app(
            config=make_config(**config),
            pipeline=FakePipeline(notes=[BELLA, MAX], transcript="two dogs"),
            store=ExamStore(),
            audio_dir=tmp_path / "incoming",
            events_keepalive_seconds=0.2,
        )
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=srv.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not srv.started:
            assert time.monotonic() < deadline, "server didn't start"
            time.sleep(0.02)
        started.append((srv, thread))
        return app, f"http://127.0.0.1:{port}"

    yield _start
    for srv, thread in started:
        srv.should_exit = True
        thread.join(timeout=5)


def _events(lines):
    """(event, data) pairs from an SSE line iterator; comments are skipped."""
    event, data = None, []
    for line in lines:
        if line == "":
            if event or data:
                yield event, "\n".join(data)
            event, data = None, []
        elif line.startswith(":"):
            yield ":", line
        elif line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:"):].strip())


def test_events_need_auth(server):
    _, url = server(backend_api_key="secret")
    response = httpx.get(f"{url}/api/events", timeout=5)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_a_finished_async_upload_is_announced_with_its_animals(server):
    _, url = server(backend_api_key="secret")
    auth = {"Authorization": "Bearer secret"}

    with httpx.Client(base_url=url, headers=auth, timeout=5) as client:
        with client.stream("GET", "/api/events") as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            events = _events(stream.iter_lines())
            assert next(events)[0] == "ready"

            upload = client.post(
                "/api/appointments",
                content=b"m4a",
                headers={"Prefer": "respond-async", "Idempotency-Key": "rec-1"},
            ).json()

            kind, data = next(e for e in events if e[0] != ":")

    assert kind == "appointment"
    assert json.loads(data) == {
        "id": upload["id"], "status": "complete", "patient_names": ["Bella", "Max"]
    }


def test_an_idle_stream_gets_keepalive_comments(server):
    _, url = server()
    with httpx.stream("GET", f"{url}/api/events", timeout=5) as stream:
        events = _events(stream.iter_lines())
        assert next(events)[0] == "ready"
        assert next(events)[0] == ":"


def test_closing_the_stream_unsubscribes(server):
    app, url = server()
    with httpx.stream("GET", f"{url}/api/events", timeout=5) as stream:
        next(_events(stream.iter_lines()))
        assert app.state.events.subscriber_count == 1

    deadline = time.monotonic() + 5
    while app.state.events.subscriber_count:
        assert time.monotonic() < deadline, "subscription leaked after disconnect"
        time.sleep(0.05)
