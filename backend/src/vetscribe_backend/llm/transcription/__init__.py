import importlib
import pkgutil
from abc import ABC, abstractmethod

from vetscribe_backend.config import BackendConfig

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
    def transcribe(self, audio_bytes: bytes) -> str: ...


class UnknownProviderError(Exception):
    pass


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
