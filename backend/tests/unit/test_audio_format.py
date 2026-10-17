import pytest

from vet_soap_notetaker_backend.llm.transcription.audio_format import (
    DEFAULT_MIME,
    M4A_MIME,
    transcription_mime,
)


@pytest.mark.parametrize("content_type", ["audio/m4a", "audio/x-m4a", "audio/mp4", "audio/aac"])
def test_aac_in_m4a_uploads_are_labelled_as_m4a(content_type):
    assert transcription_mime(content_type) == M4A_MIME


@pytest.mark.parametrize("content_type", ["audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"])
def test_wav_uploads_are_labelled_as_wav(content_type):
    assert transcription_mime(content_type) == "audio/wav"


def test_matching_ignores_case_and_parameters():
    assert transcription_mime("Audio/M4A; codecs=mp4a") == M4A_MIME


@pytest.mark.parametrize("content_type", [None, "", "application/octet-stream", "audio/ogg"])
def test_missing_or_unknown_types_fall_back_to_wav(content_type):
    # The desktop and older clients send WAV, so the fallback keeps them unchanged.
    assert transcription_mime(content_type) == DEFAULT_MIME == "audio/wav"
