import json

import httpx
import pytest
import respx

from vet_soap_notetaker.api_client import (
    GENERATE_CONNECT_TIMEOUT_SECONDS,
    ApiClient,
    ApiClientError,
    BackendUnreachableError,
    ExamNotFoundError,
    NotePendingError,
)


@respx.mock
def test_generate_soap_note_posts_audio_bytes_and_returns_parsed_note():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "Patient presented for annual checkup.",
                "objective": "Temp 101.5F, HR 120bpm.",
                "assessment": "Healthy adult canine.",
                "plan": "Continue current diet, recheck in 1 year.",
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)
    note = client.generate_soap_note(b"RIFF....fake-wav-bytes....")

    assert route.called
    request = route.calls.last.request
    assert request.content == b"RIFF....fake-wav-bytes...."
    assert note.subjective == "Patient presented for annual checkup."
    assert note.objective == "Temp 101.5F, HR 120bpm."
    assert note.assessment == "Healthy adult canine."
    assert note.plan == "Continue current diet, recheck in 1 year."


@respx.mock
def test_generate_soap_note_parses_transcript_from_response():
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "sub",
                "objective": "obj",
                "assessment": "assess",
                "plan": "plan",
                "transcript": "The owner reports the dog has been vomiting since yesterday.",
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)
    note = client.generate_soap_note(b"RIFF....")

    assert note.transcript == "The owner reports the dog has been vomiting since yesterday."


@respx.mock
def test_generate_soap_note_defaults_transcript_to_empty_when_absent():
    # Older backends respond without a transcript field; the client must not
    # crash and should surface an empty transcript rather than raising.
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "sub",
                "objective": "obj",
                "assessment": "assess",
                "plan": "plan",
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)
    note = client.generate_soap_note(b"RIFF....")

    assert note.transcript == ""


@respx.mock
def test_generate_soap_note_raises_api_client_error_on_timeout():
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        side_effect=httpx.TimeoutException("timed out")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError, match="timed out"):
        client.generate_soap_note(b"RIFF....")


@respx.mock
def test_generate_soap_note_raises_api_client_error_on_connection_refused():
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError, match="connection refused"):
        client.generate_soap_note(b"RIFF....")


@respx.mock
def test_generate_soap_note_raises_api_client_error_on_http_error_status():
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(500, json={"error": "internal server error"})
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError, match="500"):
        client.generate_soap_note(b"RIFF....")


@respx.mock
def test_generate_soap_note_sends_authorization_header_when_api_key_configured():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "sub",
                "objective": "obj",
                "assessment": "assess",
                "plan": "plan",
            },
        )
    )

    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap",
        timeout_seconds=30,
        api_key="secret-token",
    )
    client.generate_soap_note(b"RIFF....")

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-token"


@respx.mock
def test_generate_soap_note_omits_authorization_header_when_no_api_key():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "sub",
                "objective": "obj",
                "assessment": "assess",
                "plan": "plan",
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)
    client.generate_soap_note(b"RIFF....")

    request = route.calls.last.request
    assert "Authorization" not in request.headers


@respx.mock
def test_generate_soap_note_raises_api_client_error_on_malformed_json():
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(200, json={"subjective": "only one field present"})
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError, match="objective"):
        client.generate_soap_note(b"RIFF....")


@respx.mock
def test_regenerate_soap_note_posts_transcript_json_to_regenerate_endpoint():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap/regenerate").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "Owner reports limping.",
                "objective": "Left forelimb lameness.",
                "assessment": "Soft-tissue strain.",
                "plan": "Rest and NSAIDs, recheck in 2 weeks.",
                "transcript": "the owner says the dog is limping",
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)
    note = client.regenerate_soap_note("the owner says the dog is limping")

    assert route.called
    request = route.calls.last.request
    assert json.loads(request.content) == {
        "transcript": "the owner says the dog is limping"
    }
    assert note.subjective == "Owner reports limping."
    assert note.transcript == "the owner says the dog is limping"


@respx.mock
def test_regenerate_soap_note_derives_endpoint_when_base_has_trailing_slash():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap/regenerate").mock(
        return_value=httpx.Response(
            200,
            json={
                "subjective": "s",
                "objective": "o",
                "assessment": "a",
                "plan": "p",
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap/", timeout_seconds=5)
    client.regenerate_soap_note("some transcript")

    assert route.called


@respx.mock
def test_regenerate_soap_note_sends_authorization_header_when_api_key_configured():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap/regenerate").mock(
        return_value=httpx.Response(
            200,
            json={"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"},
        )
    )

    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap",
        timeout_seconds=5,
        api_key="secret-token",
    )
    client.regenerate_soap_note("transcript")

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@respx.mock
def test_regenerate_soap_note_raises_api_client_error_on_connection_refused():
    respx.post("https://vet_soap_notetaker.example.com/api/soap/regenerate").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.regenerate_soap_note("transcript")


@respx.mock
def test_regenerate_soap_note_raises_api_client_error_on_http_error_status():
    respx.post("https://vet_soap_notetaker.example.com/api/soap/regenerate").mock(
        return_value=httpx.Response(502, json={"error": "upstream provider error"})
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError, match="502"):
        client.regenerate_soap_note("transcript")


@respx.mock
def test_fetch_pending_injections_returns_requests_list():
    route = respx.get("https://vet_soap_notetaker.example.com/api/injections/pending").mock(
        return_value=httpx.Response(
            200,
            json={
                "requests": [
                    {
                        "id": "req-1",
                        "exam_id": "exam-1",
                        "created_at": "2026-09-22T00:00:00+00:00",
                        "status": "pending",
                        "outcome": None,
                        "exam": {
                            "id": "exam-1",
                            "subjective": "s",
                            "objective": "o",
                            "assessment": "a",
                            "plan": "p",
                            "transcript": "t",
                        },
                    }
                ]
            },
        )
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)
    requests = client.fetch_pending_injections()

    assert route.called
    assert len(requests) == 1
    assert requests[0]["id"] == "req-1"
    assert requests[0]["exam"]["assessment"] == "a"


@respx.mock
def test_fetch_pending_injections_sends_bearer_token_when_configured():
    route = respx.get("https://vet_soap_notetaker.example.com/api/injections/pending").mock(
        return_value=httpx.Response(200, json={"requests": []})
    )

    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5, api_key="secret"
    )
    assert client.fetch_pending_injections() == []
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@respx.mock
def test_fetch_pending_injections_raises_api_client_error_on_transport_failure():
    respx.get("https://vet_soap_notetaker.example.com/api/injections/pending").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.fetch_pending_injections()


@respx.mock
def test_fetch_pending_injections_raises_on_http_error_status():
    respx.get("https://vet_soap_notetaker.example.com/api/injections/pending").mock(
        return_value=httpx.Response(500, text="boom")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError, match="500"):
        client.fetch_pending_injections()


@respx.mock
def test_ack_injection_posts_outcome_to_the_request_endpoint():
    route = respx.post("https://vet_soap_notetaker.example.com/api/injections/req-1/ack").mock(
        return_value=httpx.Response(200, json={"id": "req-1", "status": "done"})
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)
    client.ack_injection("req-1", outcome="injected")

    assert route.called
    assert json.loads(route.calls.last.request.content) == {"outcome": "injected"}


@respx.mock
def test_ack_injection_raises_api_client_error_on_transport_failure():
    respx.post("https://vet_soap_notetaker.example.com/api/injections/req-1/ack").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.ack_injection("req-1", outcome="injected")


# --- Shared exam history (backend as single source of truth) ---------------

_EXAM_JSON = {
    "id": "exam-1",
    "created_at": "2026-09-22T00:00:01Z",
    "patient_name": "Rex",
    "subjective": "sub",
    "objective": "obj",
    "assessment": "assess",
    "plan": "plan",
    "transcript": "vet: hello",
}


@respx.mock
def test_fetch_history_returns_exams_parsed_into_dataclasses():
    route = respx.get("https://vet_soap_notetaker.example.com/api/history").mock(
        return_value=httpx.Response(200, json={"exams": [_EXAM_JSON]})
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)
    exams = client.fetch_history()

    assert route.called
    assert len(exams) == 1
    exam = exams[0]
    assert exam.id == "exam-1"
    assert exam.created_at == "2026-09-22T00:00:01Z"
    assert exam.patient_name == "Rex"
    assert exam.assessment == "assess"
    assert exam.transcript == "vet: hello"
    # soap_text renders the four structured fields for copy/inject.
    assert "assess" in exam.soap_text


@respx.mock
def test_fetch_history_sends_bearer_token_when_configured():
    route = respx.get("https://vet_soap_notetaker.example.com/api/history").mock(
        return_value=httpx.Response(200, json={"exams": []})
    )

    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5, api_key="secret"
    )
    assert client.fetch_history() == []
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@respx.mock
def test_fetch_history_raises_api_client_error_on_transport_failure():
    respx.get("https://vet_soap_notetaker.example.com/api/history").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.fetch_history()


@respx.mock
def test_fetch_history_raises_on_http_error_status():
    respx.get("https://vet_soap_notetaker.example.com/api/history").mock(
        return_value=httpx.Response(500, text="boom")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.fetch_history()


@respx.mock
def test_update_exam_puts_structured_fields_and_returns_updated_exam():
    updated = {**_EXAM_JSON, "assessment": "new-assessment", "transcript": "corrected"}
    route = respx.put("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        return_value=httpx.Response(200, json=updated)
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)
    exam = client.update_exam(
        "exam-1",
        subjective="sub",
        objective="obj",
        assessment="new-assessment",
        plan="plan",
        transcript="corrected",
    )

    assert route.called
    assert json.loads(route.calls.last.request.content) == {
        "subjective": "sub",
        "objective": "obj",
        "assessment": "new-assessment",
        "plan": "plan",
        "transcript": "corrected",
    }
    assert exam.assessment == "new-assessment"
    assert exam.transcript == "corrected"


@respx.mock
def test_update_exam_sends_bearer_token_when_configured():
    route = respx.put("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        return_value=httpx.Response(200, json=_EXAM_JSON)
    )

    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5, api_key="secret"
    )
    client.update_exam(
        "exam-1", subjective="s", objective="o", assessment="a", plan="p", transcript="t"
    )

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@respx.mock
def test_update_exam_raises_on_http_error_status():
    respx.put("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        return_value=httpx.Response(404, text="exam not found")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.update_exam(
            "exam-1", subjective="s", objective="o", assessment="a", plan="p", transcript="t"
        )


@respx.mock
def test_delete_exam_sends_delete_to_the_exam_endpoint():
    route = respx.delete("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        return_value=httpx.Response(200, json={"status": "deleted"})
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)
    client.delete_exam("exam-1")

    assert route.called


@respx.mock
def test_delete_exam_sends_bearer_token_when_configured():
    route = respx.delete("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        return_value=httpx.Response(200, json={"status": "deleted"})
    )

    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5, api_key="secret"
    )
    client.delete_exam("exam-1")

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@respx.mock
def test_delete_exam_raises_on_http_error_status():
    respx.delete("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        return_value=httpx.Response(500, text="boom")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.delete_exam("exam-1")


@respx.mock
def test_delete_exam_raises_api_client_error_on_transport_failure():
    respx.delete("https://vet_soap_notetaker.example.com/api/exams/exam-1").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=5)

    with pytest.raises(ApiClientError):
        client.delete_exam("exam-1")


_NOTE_JSON = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}


def _sent_timeout(route):
    return route.calls.last.request.extensions["timeout"]


@respx.mock
def test_generate_soap_note_waits_long_for_the_provider_but_connects_fast():
    # Transcription + note generation can take minutes, so the read timeout is
    # long -- but an unreachable backend (stale IP) must still fail fast.
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(200, json=_NOTE_JSON)
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    client.generate_soap_note(b"RIFF....")

    timeout = _sent_timeout(route)
    assert timeout["read"] == 480
    assert timeout["connect"] == GENERATE_CONNECT_TIMEOUT_SECONDS


@respx.mock
def test_generate_soap_note_uses_a_custom_generate_timeout():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(200, json=_NOTE_JSON)
    )
    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap",
        timeout_seconds=30,
        generate_timeout_seconds=600,
    )

    client.generate_soap_note(b"RIFF....")

    assert _sent_timeout(route)["read"] == 600


@respx.mock
def test_regenerate_soap_note_uses_the_long_generate_timeout():
    route = respx.post("https://vet_soap_notetaker.example.com/api/soap/regenerate").mock(
        return_value=httpx.Response(200, json=_NOTE_JSON)
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    client.regenerate_soap_note("owner reports vomiting")

    timeout = _sent_timeout(route)
    assert timeout["read"] == 480
    assert timeout["connect"] == GENERATE_CONNECT_TIMEOUT_SECONDS


@respx.mock
def test_quick_calls_keep_the_short_timeout():
    history = respx.get("https://vet_soap_notetaker.example.com/api/history").mock(
        return_value=httpx.Response(200, json={"exams": []})
    )
    pending = respx.get("https://vet_soap_notetaker.example.com/api/injections/pending").mock(
        return_value=httpx.Response(200, json={"requests": []})
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    client.fetch_history()
    client.fetch_pending_injections()

    assert _sent_timeout(history)["read"] == 30
    assert _sent_timeout(pending)["read"] == 30


_PENDING_EXAM_JSON = {
    "id": "exam-123",
    "created_at": "2026-10-13T00:00:00+00:00",
    "patient_name": None,
    "subjective": "",
    "objective": "",
    "assessment": "",
    "plan": "",
    "transcript": "ZZ_TRANSCRIPT_SENTINEL owner reports vomiting",
    "note_pending": True,
}


@respx.mock
def test_generate_soap_note_raises_note_pending_with_the_exam_id_on_202():
    # 202 = transcript saved on the backend, note generation failed. The caller
    # finishes the note via complete_note(exam_id) instead of re-uploading audio.
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(202, json=_PENDING_EXAM_JSON)
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    with pytest.raises(NotePendingError) as excinfo:
        client.generate_soap_note(b"RIFF....")

    assert excinfo.value.exam_id == "exam-123"
    # It's still an ApiClientError, so callers that don't know about it fail safe.
    assert isinstance(excinfo.value, ApiClientError)
    # The response body (with the transcript) must not leak into the message,
    # which ends up in the error flyout and the log file.
    assert "ZZ_TRANSCRIPT_SENTINEL" not in str(excinfo.value)


@respx.mock
def test_generate_soap_note_treats_a_202_without_an_exam_id_as_a_plain_error():
    respx.post("https://vet_soap_notetaker.example.com/api/soap").mock(
        return_value=httpx.Response(202, json={"unexpected": True})
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    with pytest.raises(ApiClientError) as excinfo:
        client.generate_soap_note(b"RIFF....")

    assert not isinstance(excinfo.value, NotePendingError)


@respx.mock
def test_complete_note_posts_to_the_exam_note_endpoint_and_returns_the_note():
    route = respx.post("https://vet_soap_notetaker.example.com/api/exams/exam-123/note").mock(
        return_value=httpx.Response(
            200, json={**_PENDING_EXAM_JSON, **_NOTE_JSON, "note_pending": False}
        )
    )
    client = ApiClient(
        endpoint="https://vet_soap_notetaker.example.com/api/soap",
        timeout_seconds=30,
        api_key="secret-token",
    )

    note = client.complete_note("exam-123")

    assert note.subjective == "s"
    assert note.plan == "p"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-token"
    # Note generation can take minutes: long read, short connect.
    assert _sent_timeout(route)["read"] == 480
    assert _sent_timeout(route)["connect"] == GENERATE_CONNECT_TIMEOUT_SECONDS


@respx.mock
def test_complete_note_raises_exam_not_found_on_404():
    respx.post("https://vet_soap_notetaker.example.com/api/exams/gone/note").mock(
        return_value=httpx.Response(404, json={"error": "exam not found"})
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    with pytest.raises(ExamNotFoundError):
        client.complete_note("gone")


@respx.mock
def test_complete_note_raises_api_client_error_when_note_generation_still_fails():
    respx.post("https://vet_soap_notetaker.example.com/api/exams/exam-123/note").mock(
        return_value=httpx.Response(502, json={"error": "upstream provider error"})
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    with pytest.raises(ApiClientError) as excinfo:
        client.complete_note("exam-123")

    assert not isinstance(excinfo.value, ExamNotFoundError)
    assert not isinstance(excinfo.value, BackendUnreachableError)


@respx.mock
def test_complete_note_raises_api_client_error_on_transport_failure():
    respx.post("https://vet_soap_notetaker.example.com/api/exams/exam-123/note").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    client = ApiClient(endpoint="https://vet_soap_notetaker.example.com/api/soap", timeout_seconds=30)

    # Distinct from an error *response*: the backend never answered, so the
    # offline queue doesn't count it against the note's retry limit.
    with pytest.raises(BackendUnreachableError) as excinfo:
        client.complete_note("exam-123")

    assert isinstance(excinfo.value, ApiClientError)


# --- Analytics identity headers --------------------------------------------

_BASE = "https://vet_soap_notetaker.example.com/api"
_IDENTITY = {"X-POSTHOG-DISTINCT-ID": "demo-vet-1", "X-VSN-Client": "desktop"}
_NOTE_JSON = {"id": "exam-9", "subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}


def _client_with_identity(identity=None):
    return ApiClient(
        endpoint=f"{_BASE}/soap",
        timeout_seconds=30,
        api_key="secret-token",
        extra_headers=lambda: dict(identity or _IDENTITY),
    )


@respx.mock
@pytest.mark.parametrize(
    "method, url, call",
    [
        ("POST", f"{_BASE}/soap", lambda c: c.generate_soap_note(b"RIFF")),
        ("POST", f"{_BASE}/soap/regenerate", lambda c: c.regenerate_soap_note("t")),
        ("POST", f"{_BASE}/exams/e1/note", lambda c: c.complete_note("e1")),
        ("GET", f"{_BASE}/history", lambda c: c.fetch_history()),
        ("DELETE", f"{_BASE}/exams/e1", lambda c: c.delete_exam("e1")),
        ("GET", f"{_BASE}/injections/pending", lambda c: c.fetch_pending_injections()),
        ("POST", f"{_BASE}/injections/r1/ack", lambda c: c.ack_injection("r1", "delivered")),
    ],
)
def test_every_request_carries_the_analytics_identity_headers(method, url, call):
    body = {"exams": [], "requests": [], **_NOTE_JSON}
    route = respx.route(method=method, url=url).mock(return_value=httpx.Response(200, json=body))

    call(_client_with_identity())

    headers = route.calls.last.request.headers
    assert headers["X-POSTHOG-DISTINCT-ID"] == "demo-vet-1"
    assert headers["X-VSN-Client"] == "desktop"
    assert headers["Authorization"] == "Bearer secret-token"


@respx.mock
def test_identity_headers_are_read_fresh_for_each_request():
    route = respx.get(f"{_BASE}/history").mock(return_value=httpx.Response(200, json={"exams": []}))
    identity = dict(_IDENTITY)
    client = _client_with_identity()
    client.extra_headers = lambda: dict(identity)

    client.fetch_history()
    identity["X-POSTHOG-DISTINCT-ID"] = "someone-else"
    client.fetch_history()

    assert route.calls.last.request.headers["X-POSTHOG-DISTINCT-ID"] == "someone-else"


@respx.mock
def test_generate_soap_note_sends_the_recording_length_and_keeps_the_exam_id():
    route = respx.post(f"{_BASE}/soap").mock(return_value=httpx.Response(200, json=_NOTE_JSON))

    note = _client_with_identity().generate_soap_note(b"RIFF", audio_duration_ms=93500)

    assert route.calls.last.request.headers["X-Audio-Duration-Ms"] == "93500"
    assert note.exam_id == "exam-9"


@respx.mock
def test_generate_soap_note_omits_the_recording_length_when_unknown():
    route = respx.post(f"{_BASE}/soap").mock(return_value=httpx.Response(200, json=_NOTE_JSON))

    ApiClient(endpoint=f"{_BASE}/soap", timeout_seconds=30).generate_soap_note(b"RIFF")

    assert "X-Audio-Duration-Ms" not in route.calls.last.request.headers


@respx.mock
def test_regenerate_soap_note_names_the_exam_when_given():
    route = respx.post(f"{_BASE}/soap/regenerate").mock(
        return_value=httpx.Response(200, json=_NOTE_JSON)
    )

    ApiClient(endpoint=f"{_BASE}/soap", timeout_seconds=30).regenerate_soap_note(
        "t", exam_id="exam-9"
    )

    assert json.loads(route.calls.last.request.content) == {"transcript": "t", "exam_id": "exam-9"}


@respx.mock
def test_generate_soap_note_raises_backend_unreachable_when_there_is_no_answer():
    # Lets the pipeline (and its analytics) tell "backend down" from "provider failed".
    respx.post(f"{_BASE}/soap").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(BackendUnreachableError):
        ApiClient(endpoint=f"{_BASE}/soap", timeout_seconds=30).generate_soap_note(b"RIFF")
