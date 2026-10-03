import pytest

from vetscribe_backend.llm.note_generation import UnknownProviderError, get_note_generator
from vetscribe_backend.llm.note_generation.anthropic_note_generator import AnthropicNoteGenerator
from vetscribe_backend.llm.note_generation.gemini_note_generator import GeminiNoteGenerator
from vetscribe_backend.llm.note_generation.ollama_note_generator import OllamaNoteGenerator
from vetscribe_backend.llm.note_generation.openai_note_generator import OpenAiNoteGenerator


def test_get_note_generator_returns_openai_generator(make_config):
    generator = get_note_generator(make_config(note_provider="openai"))
    assert isinstance(generator, OpenAiNoteGenerator)


def test_get_note_generator_returns_anthropic_generator(make_config):
    generator = get_note_generator(make_config(note_provider="anthropic"))
    assert isinstance(generator, AnthropicNoteGenerator)


def test_get_note_generator_returns_gemini_generator(make_config):
    generator = get_note_generator(make_config(note_provider="gemini"))
    assert isinstance(generator, GeminiNoteGenerator)


def test_get_note_generator_returns_ollama_generator(make_config):
    generator = get_note_generator(make_config(note_provider="ollama"))
    assert isinstance(generator, OllamaNoteGenerator)


def test_get_note_generator_raises_on_unknown_provider(make_config):
    with pytest.raises(UnknownProviderError, match="carrier-pigeon"):
        get_note_generator(make_config(note_provider="carrier-pigeon"))
