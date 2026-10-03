import httpx
import pytest
import respx

from vetscribe_backend.llm.transcription.gemini_transcriber import (
    GeminiTranscriber,
    TranscriptionError,
)


def _text_parts(request):
    import json

    body = json.loads(request.content)
    return [
        part["text"]
        for content in body["contents"]
        for part in content["parts"]
        if "text" in part
    ]


@respx.mock
def test_transcribe_sends_base64_audio_and_returns_text():
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "patient is a 5 year old lab"}]}}
                ]
            },
        )
    )

    transcriber = GeminiTranscriber(api_key="key123", model="gemini-2.0-flash")
    text = transcriber.transcribe(b"RIFF....fake-wav-bytes....")

    assert text == "patient is a 5 year old lab"
    request = route.calls.last.request
    assert request.url.params["key"] == "key123"


@respx.mock
def test_transcribe_prompt_requests_speaker_diarization():
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Veterinarian: hi"}]}}]},
        )
    )

    GeminiTranscriber(api_key="key123", model="gemini-2.0-flash").transcribe(b"RIFF....")

    prompt = " ".join(_text_parts(route.calls.last.request)).lower()
    assert "diarization" in prompt
    assert "veterinarian:" in prompt
    assert "owner:" in prompt


@respx.mock
def test_transcribe_raises_on_http_error():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(return_value=httpx.Response(403, json={"error": "invalid key"}))

    transcriber = GeminiTranscriber(api_key="bad-key", model="gemini-2.0-flash")

    with pytest.raises(httpx.HTTPStatusError):
        transcriber.transcribe(b"RIFF....")


@respx.mock
def test_transcribe_raises_transcription_error_when_no_candidates_returned():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}},
        )
    )

    transcriber = GeminiTranscriber(api_key="key123", model="gemini-2.0-flash")

    with pytest.raises(TranscriptionError, match="SAFETY"):
        transcriber.transcribe(b"RIFF....fake-wav-bytes....")
