import httpx
import pytest
import respx

from vet_soap_notetaker_backend.llm.transcription import NoSpeechError
from vet_soap_notetaker_backend.llm.transcription.openai_transcriber import OpenAiTranscriber


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


def _uploaded_file_header(request) -> str:
    # The multipart part header for the audio file, e.g.
    # 'Content-Disposition: form-data; name="file"; filename="recording.m4a"\r\nContent-Type: audio/mp4'
    body = request.content.decode("latin-1")
    start = body.index('name="file"')
    return body[start : body.index("\r\n\r\n", start)]


@respx.mock
def test_transcribe_uploads_m4a_audio_as_m4a():
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hi"})
    )

    OpenAiTranscriber(api_key="sk-test", model="whisper-1").transcribe(
        b"m4a-bytes", mime_type="audio/mp4"
    )

    header = _uploaded_file_header(route.calls.last.request)
    assert 'filename="recording.m4a"' in header
    assert "Content-Type: audio/mp4" in header


@respx.mock
def test_transcribe_uploads_wav_audio_as_wav_by_default():
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hi"})
    )

    OpenAiTranscriber(api_key="sk-test", model="whisper-1").transcribe(b"RIFF....")

    header = _uploaded_file_header(route.calls.last.request)
    assert 'filename="recording.wav"' in header
    assert "Content-Type: audio/wav" in header


@pytest.mark.parametrize("text", ["", "   \n"])
@respx.mock
def test_transcribe_raises_no_speech_error_on_an_empty_transcript(text):
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": text})
    )

    with pytest.raises(NoSpeechError):
        OpenAiTranscriber(api_key="sk-test", model="whisper-1").transcribe(b"RIFF....")
