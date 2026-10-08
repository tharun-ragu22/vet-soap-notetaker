import json

import httpx
import pytest
import respx

from vet_soap_notetaker_backend.llm import http_retry
from vet_soap_notetaker_backend.llm.transcription import gemini_transcriber as gt_module
from vet_soap_notetaker_backend.llm.transcription.gemini_transcriber import (
    GeminiTranscriber,
    TranscriptionError,
)

# Files API fixture URLs (large-recording fallback path).
GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
)
UPLOAD_START_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
UPLOAD_SESSION_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files/session-xyz"
FILE_NAME = "files/abc123"
FILE_URI = "https://generativelanguage.googleapis.com/v1beta/files/abc123"
FILE_RESOURCE_URL = "https://generativelanguage.googleapis.com/v1beta/files/abc123"


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(http_retry.time, "sleep", lambda seconds: None)


@pytest.fixture
def no_poll_sleep(monkeypatch):
    monkeypatch.setattr(gt_module.time, "sleep", lambda seconds: None)


def _audio_part(request):
    """Return the single part of a generateContent body that carries the audio."""
    body = json.loads(request.content)
    for part in body["contents"][0]["parts"]:
        if "inline_data" in part or "file_data" in part:
            return part
    return None


def _candidates(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _large_transcriber():
    # A tiny ceiling forces the Files API path with a few bytes -- no need to
    # actually allocate 80 MB to exercise the "too large" branch.
    return GeminiTranscriber(
        api_key="key123", model="gemini-2.0-flash", inline_max_bytes=5
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


def test_transcriber_defaults_to_120_second_timeout():
    transcriber = GeminiTranscriber(api_key="key123", model="gemini-2.5-flash")
    assert transcriber.timeout_seconds == 120


@respx.mock
def test_transcribe_retries_transient_server_error_then_succeeds(no_sleep):
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(
        side_effect=[
            httpx.Response(503, json={"error": "overloaded"}),
            httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            ),
        ]
    )

    transcriber = GeminiTranscriber(api_key="key123", model="gemini-2.0-flash")
    text = transcriber.transcribe(b"RIFF....")

    assert text == "ok"
    assert route.call_count == 2


@respx.mock
def test_transcribe_does_not_retry_auth_failure(no_sleep):
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    ).mock(return_value=httpx.Response(403, json={"error": "invalid key"}))

    transcriber = GeminiTranscriber(api_key="bad-key", model="gemini-2.0-flash")

    with pytest.raises(httpx.HTTPStatusError):
        transcriber.transcribe(b"RIFF....")
    assert route.call_count == 1


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


# --- Files API fallback for oversized recordings -----------------------------


def test_inline_max_bytes_defaults_to_80_mib():
    transcriber = GeminiTranscriber(api_key="k", model="m")
    assert transcriber.inline_max_bytes == 80 * 1024 * 1024


def test_files_api_timeout_defaults_to_300_seconds():
    transcriber = GeminiTranscriber(api_key="k", model="m")
    assert transcriber.files_api_timeout_seconds == 300


@respx.mock
def test_small_audio_uses_inline_and_never_uploads():
    upload = respx.post(UPLOAD_START_URL).mock(return_value=httpx.Response(200))
    gen = respx.post(GENERATE_URL).mock(return_value=httpx.Response(200, json=_candidates("ok")))

    # Default 80 MiB ceiling -- a tiny clip stays on the inline path.
    transcriber = GeminiTranscriber(api_key="key123", model="gemini-2.0-flash")
    text = transcriber.transcribe(b"small-audio")

    assert text == "ok"
    assert upload.call_count == 0
    assert "inline_data" in _audio_part(gen.calls.last.request)


@respx.mock
def test_large_audio_uploads_via_files_api_and_returns_transcript():
    start = respx.post(UPLOAD_START_URL).mock(
        return_value=httpx.Response(200, headers={"X-Goog-Upload-URL": UPLOAD_SESSION_URL})
    )
    finalize = respx.post(UPLOAD_SESSION_URL).mock(
        return_value=httpx.Response(
            200, json={"file": {"name": FILE_NAME, "uri": FILE_URI, "state": "ACTIVE"}}
        )
    )
    respx.delete(FILE_RESOURCE_URL).mock(return_value=httpx.Response(200))
    gen = respx.post(GENERATE_URL).mock(
        return_value=httpx.Response(200, json=_candidates("long transcript"))
    )

    text = _large_transcriber().transcribe(b"this-is-big-audio")

    assert text == "long transcript"
    assert start.call_count == 1
    assert finalize.calls.last.request.content == b"this-is-big-audio"
    part = _audio_part(gen.calls.last.request)
    assert "inline_data" not in part
    assert part["file_data"]["file_uri"] == FILE_URI


@respx.mock
def test_files_api_polls_until_active(no_poll_sleep):
    respx.post(UPLOAD_START_URL).mock(
        return_value=httpx.Response(200, headers={"X-Goog-Upload-URL": UPLOAD_SESSION_URL})
    )
    respx.post(UPLOAD_SESSION_URL).mock(
        return_value=httpx.Response(
            200, json={"file": {"name": FILE_NAME, "uri": FILE_URI, "state": "PROCESSING"}}
        )
    )
    poll = respx.get(FILE_RESOURCE_URL).mock(
        side_effect=[
            httpx.Response(200, json={"name": FILE_NAME, "uri": FILE_URI, "state": "PROCESSING"}),
            httpx.Response(200, json={"name": FILE_NAME, "uri": FILE_URI, "state": "ACTIVE"}),
        ]
    )
    respx.delete(FILE_RESOURCE_URL).mock(return_value=httpx.Response(200))
    respx.post(GENERATE_URL).mock(return_value=httpx.Response(200, json=_candidates("done")))

    assert _large_transcriber().transcribe(b"big-audio") == "done"
    assert poll.call_count == 2


@respx.mock
def test_files_api_raises_on_failed_state(no_poll_sleep):
    respx.post(UPLOAD_START_URL).mock(
        return_value=httpx.Response(200, headers={"X-Goog-Upload-URL": UPLOAD_SESSION_URL})
    )
    respx.post(UPLOAD_SESSION_URL).mock(
        return_value=httpx.Response(
            200, json={"file": {"name": FILE_NAME, "uri": FILE_URI, "state": "PROCESSING"}}
        )
    )
    respx.get(FILE_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"name": FILE_NAME, "state": "FAILED"})
    )
    respx.delete(FILE_RESOURCE_URL).mock(return_value=httpx.Response(200))

    with pytest.raises(TranscriptionError):
        _large_transcriber().transcribe(b"big-audio")


@respx.mock
def test_files_api_deletes_uploaded_file_after_success():
    respx.post(UPLOAD_START_URL).mock(
        return_value=httpx.Response(200, headers={"X-Goog-Upload-URL": UPLOAD_SESSION_URL})
    )
    respx.post(UPLOAD_SESSION_URL).mock(
        return_value=httpx.Response(
            200, json={"file": {"name": FILE_NAME, "uri": FILE_URI, "state": "ACTIVE"}}
        )
    )
    delete = respx.delete(FILE_RESOURCE_URL).mock(return_value=httpx.Response(200))
    respx.post(GENERATE_URL).mock(return_value=httpx.Response(200, json=_candidates("x")))

    _large_transcriber().transcribe(b"big-audio")

    assert delete.call_count == 1


@respx.mock
def test_files_api_delete_failure_does_not_break_transcription():
    respx.post(UPLOAD_START_URL).mock(
        return_value=httpx.Response(200, headers={"X-Goog-Upload-URL": UPLOAD_SESSION_URL})
    )
    respx.post(UPLOAD_SESSION_URL).mock(
        return_value=httpx.Response(
            200, json={"file": {"name": FILE_NAME, "uri": FILE_URI, "state": "ACTIVE"}}
        )
    )
    respx.delete(FILE_RESOURCE_URL).mock(return_value=httpx.Response(500))
    respx.post(GENERATE_URL).mock(return_value=httpx.Response(200, json=_candidates("still-ok")))

    assert _large_transcriber().transcribe(b"big-audio") == "still-ok"
