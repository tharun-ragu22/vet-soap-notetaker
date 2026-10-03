import json

import httpx
import pytest
import respx

from vetscribe_backend.llm.note_generation.gemini_note_generator import GeminiNoteGenerator
from vetscribe_backend.llm.note_generation.parsing import NoteParsingError

SOAP_PAYLOAD = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}


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
    note = generator.generate("transcript text")

    assert note.plan == "p"
    request = route.calls.last.request
    assert request.url.params["key"] == "key123"
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
