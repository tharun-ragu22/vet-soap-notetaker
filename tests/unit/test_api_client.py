import json

import httpx
import pytest
import respx

from vet_soap_notetaker.api_client import ApiClient, ApiClientError


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
