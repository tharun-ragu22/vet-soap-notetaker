import json

import httpx
import pytest
import respx

from vet_soap_notetaker_backend.llm import http_retry
from vet_soap_notetaker_backend.llm.note_generation.gemini_note_generator import GeminiNoteGenerator
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError

SOAP_PAYLOAD = {
    "patients": [
        {"patient_name": "Bella", "subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}
    ]
}
TWO_PATIENTS = {
    "patients": [
        {"patient_name": "Bella", "subjective": "s1", "objective": "o1", "assessment": "a1", "plan": "p1"},
        {"patient_name": "Max", "subjective": "s2", "objective": "o2", "assessment": "a2", "plan": "p2"},
    ]
}


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(http_retry.time, "sleep", lambda seconds: None)


@respx.mock
def test_generate_sends_system_instruction_and_parses_response():
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(SOAP_PAYLOAD)}]}}
                ]
            },
        )
    )

    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.0-flash")
    [note] = generator.generate("transcript text")

    assert note.plan == "p"
    request = route.calls.last.request
    # The key goes in a header, never the URL: httpx error text includes the
    # full URL, and that text used to reach the vet's screen and logs.
    assert request.headers["x-goog-api-key"] == "key123"
    assert "key" not in request.url.params
    sent_body = json.loads(request.content)
    assert "SOAP" in sent_body["system_instruction"]["parts"][0]["text"]
    assert sent_body["contents"][0]["parts"][0]["text"] == "transcript text"


@respx.mock
def test_generate_raises_note_parsing_error_on_malformed_json():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "nope"}]}}]}
        )
    )

    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.0-flash")

    with pytest.raises(NoteParsingError):
        generator.generate("transcript")


@respx.mock
def test_generate_raises_on_http_error():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(return_value=httpx.Response(403, json={"error": "invalid key"}))

    generator = GeminiNoteGenerator(api_key="bad-key", model="gemini-2.0-flash")

    with pytest.raises(httpx.HTTPStatusError):
        generator.generate("transcript")


def test_note_generator_defaults_to_120_second_timeout():
    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.5-flash")
    assert generator.timeout_seconds == 120


@respx.mock
def test_generate_retries_transient_server_error_then_succeeds(no_sleep):
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        side_effect=[
            httpx.Response(503, json={"error": "overloaded"}),
            httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps(SOAP_PAYLOAD)}]}}]},
            ),
        ]
    )

    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.0-flash")
    [note] = generator.generate("transcript text")

    assert note.plan == "p"
    assert route.call_count == 2


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


@respx.mock
def test_generate_returns_one_note_per_patient():
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(TWO_PATIENTS)}]}}]},
        )
    )

    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.0-flash")
    notes = generator.generate("transcript")

    assert [(n.patient_name, n.plan) for n in notes] == [("Bella", "p1"), ("Max", "p2")]


@pytest.mark.parametrize(
    "body",
    [
        # A blocked prompt comes back with promptFeedback and no candidates.
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        {"candidates": [{"finishReason": "SAFETY"}]},
        {"candidates": [{"content": {"parts": []}}]},
    ],
)
@respx.mock
def test_generate_raises_note_parsing_error_when_the_reply_has_no_content(body):
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=body))

    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.0-flash")

    with pytest.raises(NoteParsingError):
        generator.generate("transcript")


@respx.mock
def test_generate_raises_note_parsing_error_when_the_reply_is_not_json():
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, text="<html>gateway</html>"))

    generator = GeminiNoteGenerator(api_key="key123", model="gemini-2.0-flash")

    with pytest.raises(NoteParsingError):
        generator.generate("transcript")
