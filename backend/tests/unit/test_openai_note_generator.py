import json

import httpx
import pytest
import respx

from vet_soap_notetaker_backend.llm.note_generation.openai_note_generator import OpenAiNoteGenerator
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError

SOAP_PAYLOAD = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}


@respx.mock
def test_generate_parses_json_content_into_soap_note():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(SOAP_PAYLOAD)}}]}
        )
    )

    generator = OpenAiNoteGenerator(api_key="sk-test", model="gpt-4o-mini")
    note = generator.generate("some transcript")

    assert note.subjective == "s"
    assert note.objective == "o"
    assert note.assessment == "a"
    assert note.plan == "p"


@respx.mock
def test_generate_sends_system_prompt_and_transcript():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(SOAP_PAYLOAD)}}]}
        )
    )

    generator = OpenAiNoteGenerator(api_key="sk-test", model="gpt-4o-mini")
    generator.generate("owner reports vomiting since yesterday")

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["messages"][0]["role"] == "system"
    assert "SOAP" in sent_body["messages"][0]["content"]
    assert sent_body["messages"][1]["content"] == "owner reports vomiting since yesterday"
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test"


@respx.mock
def test_generate_raises_note_parsing_error_on_malformed_json():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not json at all"}}]}
        )
    )

    generator = OpenAiNoteGenerator(api_key="sk-test", model="gpt-4o-mini")

    with pytest.raises(NoteParsingError):
        generator.generate("transcript")


@respx.mock
def test_generate_raises_on_http_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )

    generator = OpenAiNoteGenerator(api_key="bad-key", model="gpt-4o-mini")

    with pytest.raises(httpx.HTTPStatusError):
        generator.generate("transcript")
