import httpx
import pytest
import respx

from vetscribe_backend.llm.transcription.openai_transcriber import OpenAiTranscriber


@respx.mock
def test_transcribe_posts_audio_and_returns_text():
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "patient is a 5 year old lab"})
    )

    transcriber = OpenAiTranscriber(api_key="sk-test", model="whisper-1")
    text = transcriber.transcribe(b"RIFF....fake-wav-bytes....")

    assert text == "patient is a 5 year old lab"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-test"


@respx.mock
def test_transcribe_raises_on_http_error():
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )

    transcriber = OpenAiTranscriber(api_key="bad-key", model="whisper-1")

    with pytest.raises(httpx.HTTPStatusError):
        transcriber.transcribe(b"RIFF....")
