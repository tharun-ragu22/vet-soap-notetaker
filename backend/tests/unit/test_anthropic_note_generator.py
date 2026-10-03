import json

import httpx
import pytest
import respx

from vetscribe_backend.llm.note_generation.anthropic_note_generator import AnthropicNoteGenerator
from vetscribe_backend.llm.note_generation.parsing import NoteParsingError

SOAP_PAYLOAD = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}


@respx.mock
def test_generate_sends_system_prompt_and_parses_response():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, json={"content": [{"type": "text", "text": json.dumps(SOAP_PAYLOAD)}]}
        )
    )

    generator = AnthropicNoteGenerator(api_key="sk-ant", model="claude-sonnet-4-5")
    note = generator.generate("transcript text")

    assert note.plan == "p"
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sk-ant"
    sent_body = json.loads(request.content)
    assert "SOAP" in sent_body["system"]
    assert sent_body["messages"][0]["content"] == "transcript text"


@respx.mock
def test_generate_raises_note_parsing_error_on_malformed_json():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "nope"}]})
    )

    generator = AnthropicNoteGenerator(api_key="sk-ant", model="claude-sonnet-4-5")

    with pytest.raises(NoteParsingError):
        generator.generate("transcript")


@respx.mock
def test_generate_raises_on_http_error():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )

    generator = AnthropicNoteGenerator(api_key="bad-key", model="claude-sonnet-4-5")

    with pytest.raises(httpx.HTTPStatusError):
        generator.generate("transcript")
