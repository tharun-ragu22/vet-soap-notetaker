import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _default_dotenv_path() -> Path:
    """Where to look for the ``.env`` holding provider keys.

    In a dev checkout that's ``backend/.env`` (two levels up from this module).
    In a PyInstaller-frozen build ``__file__`` lives inside the unpacked bundle,
    so that relative path points at a temp dir, not the installed app -- the
    combined installer drops the keys ``.env`` next to the backend executable, so
    look there instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(__file__).resolve().parents[2] / ".env"


@dataclass
class BackendConfig:
    transcription_provider: str
    note_provider: str
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_transcription_model: str = "whisper-1"
    openai_note_model: str = "gpt-4o-mini"
    anthropic_note_model: str = "claude-sonnet-4-5"
    gemini_transcription_model: str = "gemini-2.5-flash"
    gemini_note_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_note_model: str = "gemma4:e4b"
    backend_api_key: str = ""

    @classmethod
    def from_env(cls, dotenv_path: Path | str | None = None) -> "BackendConfig":
        load_dotenv(dotenv_path or _default_dotenv_path())
        return cls(
            transcription_provider=os.environ.get("VETSCRIBE_TRANSCRIPTION_PROVIDER", "openai"),
            note_provider=os.environ.get("VETSCRIBE_NOTE_PROVIDER", "openai"),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            openai_transcription_model=os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
            openai_note_model=os.environ.get("OPENAI_NOTE_MODEL", "gpt-4o-mini"),
            anthropic_note_model=os.environ.get("ANTHROPIC_NOTE_MODEL", "claude-sonnet-4-5"),
            gemini_transcription_model=os.environ.get(
                "GEMINI_TRANSCRIPTION_MODEL", "gemini-2.5-flash"
            ),
            gemini_note_model=os.environ.get("GEMINI_NOTE_MODEL", "gemini-2.5-flash"),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_note_model=os.environ.get("OLLAMA_NOTE_MODEL", "gemma4:e4b"),
            backend_api_key=os.environ.get("VETSCRIBE_BACKEND_API_KEY", ""),
        )
