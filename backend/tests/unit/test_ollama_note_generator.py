import json

import httpx
import pytest
import respx

from vet_soap_notetaker_backend.llm.note_generation.ollama_note_generator import OllamaNoteGenerator
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError

SOAP_PAYLOAD = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}


@respx.mock
def test_generate_parses_json_content_into_soap_note():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(SOAP_PAYLOAD)}}]}
        )
    )

    generator = OllamaNoteGenerator(base_url="http://localhost:11434", model="gemma4:e4b")
    note = generator.generate("some transcript")

    assert note.subjective == "s"
    assert note.objective == "o"
    assert note.assessment == "a"
    assert note.plan == "p"


@respx.mock
def test_generate_sends_system_prompt_and_transcript():
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(SOAP_PAYLOAD)}}]}
        )
    )

    generator = OllamaNoteGenerator(base_url="http://localhost:11434", model="gemma4:e4b")
    generator.generate("owner reports vomiting since yesterday")

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["model"] == "gemma4:e4b"
    assert sent_body["messages"][0]["role"] == "system"
    assert "SOAP" in sent_body["messages"][0]["content"]
    assert sent_body["messages"][1]["content"] == "owner reports vomiting since yesterday"


@respx.mock
def test_generate_strips_trailing_slash_from_base_url():
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(SOAP_PAYLOAD)}}]}
        )
    )

    generator = OllamaNoteGenerator(base_url="http://localhost:11434/", model="gemma4:e4b")
    generator.generate("transcript")

    assert route.calls.last.request.url == "http://localhost:11434/v1/chat/completions"


@respx.mock
def test_generate_raises_note_parsing_error_on_malformed_json():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not json at all"}}]}
        )
    )

    generator = OllamaNoteGenerator(base_url="http://localhost:11434", model="gemma4:e4b")

    with pytest.raises(NoteParsingError):
        generator.generate("transcript")


@respx.mock
def test_generate_raises_on_http_error():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "model not loaded"})
    )

    generator = OllamaNoteGenerator(base_url="http://localhost:11434", model="gemma4:e4b")

    with pytest.raises(httpx.HTTPStatusError):
        generator.generate("transcript")
