import httpx

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.note_generation import NoteGenerator
from vet_soap_notetaker_backend.llm.note_generation.parsing import parse_soap_json
from vet_soap_notetaker_backend.llm.prompts import SOAP_SYSTEM_PROMPT
from vet_soap_notetaker_backend.schemas import SoapNote


class OpenAiNoteGenerator(NoteGenerator):
    provider_name = "openai"
    ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: BackendConfig) -> "OpenAiNoteGenerator":
        return cls(api_key=config.openai_api_key, model=config.openai_note_model)

    def generate(self, transcript: str) -> SoapNote:
        response = httpx.post(
            self.ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SOAP_SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return parse_soap_json(content)
