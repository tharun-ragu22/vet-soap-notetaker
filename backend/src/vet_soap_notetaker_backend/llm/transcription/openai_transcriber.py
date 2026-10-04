import httpx

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.transcription import Transcriber


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

    def transcribe(self, audio_bytes: bytes) -> str:
        response = httpx.post(
            self.ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": ("recording.wav", audio_bytes, "audio/wav")},
            data={"model": self.model},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()["text"]
