import httpx

from vetscribe_backend.config import BackendConfig
from vetscribe_backend.llm.note_generation import NoteGenerator
from vetscribe_backend.llm.note_generation.parsing import parse_soap_json
from vetscribe_backend.llm.prompts import SOAP_SYSTEM_PROMPT
from vetscribe_backend.schemas import SoapNote

ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiNoteGenerator(NoteGenerator):
    provider_name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: BackendConfig) -> "GeminiNoteGenerator":
        return cls(api_key=config.gemini_api_key, model=config.gemini_note_model)

    def generate(self, transcript: str) -> SoapNote:
        response = httpx.post(
            ENDPOINT_TEMPLATE.format(model=self.model),
            params={"key": self.api_key},
            json={
                "system_instruction": {"parts": [{"text": SOAP_SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": transcript}]}],
                "generationConfig": {"response_mime_type": "application/json"},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return parse_soap_json(content)
