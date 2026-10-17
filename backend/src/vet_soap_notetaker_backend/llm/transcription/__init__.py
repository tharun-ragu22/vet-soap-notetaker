import importlib
import pkgutil
import re
from abc import ABC, abstractmethod

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.transcription.audio_format import DEFAULT_MIME

_registry: dict[str, type["Transcriber"]] = {}


class Transcriber(ABC):
    provider_name: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if getattr(cls, "provider_name", None):
            _registry[cls.provider_name] = cls

    @classmethod
    @abstractmethod
    def from_config(cls, config: BackendConfig) -> "Transcriber": ...

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, mime_type: str = DEFAULT_MIME) -> str: ...


class UnknownProviderError(Exception):
    pass


class NoSpeechError(Exception):
    """The recording has no intelligible speech, so there is nothing to make a note
    from. Deliberately not a TranscriptionError: it isn't a provider failure (no
    502), and retrying the same audio can't help."""


_NO_SPEECH_REPLY = re.compile(r"\W*no_speech\W*", re.IGNORECASE)
_SPEAKER_LABEL = re.compile(r"^\s*[A-Za-z][\w ]{0,30}:", re.MULTILINE)


def require_speech(transcript: str) -> str:
    """Return the transcript, or raise NoSpeechError if it holds no actual words:
    empty, the NO_SPEECH reply, or nothing but speaker labels and [inaudible]."""
    words = _SPEAKER_LABEL.sub("", transcript).replace("[inaudible]", "")
    if not words.strip() or _NO_SPEECH_REPLY.fullmatch(words):
        raise NoSpeechError()
    return transcript


def _discover_providers() -> None:
    for module_info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module_info.name}")


def get_transcriber(config: BackendConfig) -> Transcriber:
    _discover_providers()
    try:
        transcriber_cls = _registry[config.transcription_provider]
    except KeyError:
        raise UnknownProviderError(
            f"unknown transcription provider: {config.transcription_provider}"
        ) from None
    return transcriber_cls.from_config(config)
