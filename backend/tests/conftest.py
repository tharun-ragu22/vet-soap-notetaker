import pytest

from vet_soap_notetaker_backend.config import BackendConfig


@pytest.fixture
def make_config():
    def _make(**overrides):
        base = dict(
            transcription_provider="openai",
            note_provider="openai",
            openai_api_key="sk-test",
            anthropic_api_key="",
            gemini_api_key="",
            openai_transcription_model="whisper-1",
            openai_note_model="gpt-4o-mini",
            anthropic_note_model="claude-sonnet-4-5",
            gemini_transcription_model="gemini-2.0-flash",
            gemini_note_model="gemini-2.0-flash",
            ollama_base_url="http://localhost:11434",
            ollama_note_model="gemma4:e4b",
            backend_api_key="",
        )
        base.update(overrides)
        return BackendConfig(**base)

    return _make
