import base64

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.http_retry import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    post_with_retries,
)
from vet_soap_notetaker_backend.llm.transcription import Transcriber

ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

TRANSCRIPTION_PROMPT = (
    "Transcribe this veterinary exam-room audio verbatim with speaker diarization. "
    "Attribute every utterance to a speaker and start each speaker's turn on its own line "
    'prefixed with a label followed by a colon, e.g. "Veterinarian:" and "Owner:". '
    'Use "Veterinarian:", "Owner:", and "Technician:" when the role is clear from context; '
    'otherwise fall back to "Speaker 1:", "Speaker 2:", and so on, keeping each speaker\'s '
    "label consistent throughout. Do not add any commentary, headings, or summary. "
    "Respond with only the labelled transcript text."
)


class TranscriptionError(Exception):
    pass


class GeminiTranscriber(Transcriber):
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @classmethod
    def from_config(cls, config: BackendConfig) -> "GeminiTranscriber":
        return cls(api_key=config.gemini_api_key, model=config.gemini_transcription_model)

    def transcribe(self, audio_bytes: bytes) -> str:
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        response = post_with_retries(
            url=ENDPOINT_TEMPLATE.format(model=self.model),
            params={"key": self.api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": TRANSCRIPTION_PROMPT},
                            {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
                        ]
                    }
                ]
            },
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            block_reason = data.get("promptFeedback", {}).get("blockReason")
            finish_reason = (data.get("candidates") or [{}])[0].get("finishReason")
            raise TranscriptionError(
                "Gemini returned no transcribable content "
                f"(blockReason={block_reason}, finishReason={finish_reason}); "
                "the audio may be empty, silent, or blocked"
            ) from exc
