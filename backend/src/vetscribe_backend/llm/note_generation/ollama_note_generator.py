import httpx

from vetscribe_backend.config import BackendConfig
from vetscribe_backend.llm.note_generation import NoteGenerator
from vetscribe_backend.llm.note_generation.parsing import parse_soap_json
from vetscribe_backend.llm.prompts import SOAP_SYSTEM_PROMPT
from vetscribe_backend.schemas import SoapNote


class OllamaNoteGenerator(NoteGenerator):
    provider_name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: BackendConfig) -> "OllamaNoteGenerator":
        return cls(base_url=config.ollama_base_url, model=config.ollama_note_model)

    def generate(self, transcript: str) -> SoapNote:
        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
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
