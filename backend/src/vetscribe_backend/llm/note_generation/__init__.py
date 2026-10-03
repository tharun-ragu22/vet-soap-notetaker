import importlib
import pkgutil
from abc import ABC, abstractmethod

from vetscribe_backend.config import BackendConfig
from vetscribe_backend.schemas import SoapNote

_registry: dict[str, type["NoteGenerator"]] = {}


class NoteGenerator(ABC):
    provider_name: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if getattr(cls, "provider_name", None):
            _registry[cls.provider_name] = cls

    @classmethod
    @abstractmethod
    def from_config(cls, config: BackendConfig) -> "NoteGenerator": ...

    @abstractmethod
    def generate(self, transcript: str) -> SoapNote: ...


class UnknownProviderError(Exception):
    pass


def _discover_providers() -> None:
    for module_info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module_info.name}")


def get_note_generator(config: BackendConfig) -> NoteGenerator:
    _discover_providers()
    try:
        generator_cls = _registry[config.note_provider]
    except KeyError:
        raise UnknownProviderError(f"unknown note provider: {config.note_provider}") from None
    return generator_cls.from_config(config)
