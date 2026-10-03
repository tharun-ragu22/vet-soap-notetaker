import pytest

from vetscribe_backend.llm.transcription import UnknownProviderError, get_transcriber
from vetscribe_backend.llm.transcription.gemini_transcriber import GeminiTranscriber
from vetscribe_backend.llm.transcription.openai_transcriber import OpenAiTranscriber


def test_get_transcriber_returns_openai_transcriber_for_openai_provider(make_config):
    transcriber = get_transcriber(make_config(transcription_provider="openai"))
    assert isinstance(transcriber, OpenAiTranscriber)


def test_get_transcriber_returns_gemini_transcriber_for_gemini_provider(make_config):
    transcriber = get_transcriber(make_config(transcription_provider="gemini"))
    assert isinstance(transcriber, GeminiTranscriber)


def test_get_transcriber_raises_on_unknown_provider(make_config):
    with pytest.raises(UnknownProviderError, match="carrier-pigeon"):
        get_transcriber(make_config(transcription_provider="carrier-pigeon"))
