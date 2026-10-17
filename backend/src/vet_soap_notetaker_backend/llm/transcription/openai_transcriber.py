import httpx

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.transcription import Transcriber, require_speech
from vet_soap_notetaker_backend.llm.transcription.audio_format import DEFAULT_MIME, M4A_MIME


class OpenAiTranscriber(Transcriber):
    provider_name = "openai"
    ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: BackendConfig) -> "OpenAiTranscriber":
        return cls(api_key=config.openai_api_key, model=config.openai_transcription_model)

    def transcribe(self, audio_bytes: bytes, mime_type: str = DEFAULT_MIME) -> str:
        # The filename extension is how the API tells the formats apart.
        extension = "m4a" if mime_type == M4A_MIME else "wav"
        response = httpx.post(
            self.ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (f"recording.{extension}", audio_bytes, mime_type)},
            data={"model": self.model},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return require_speech(response.json()["text"])
