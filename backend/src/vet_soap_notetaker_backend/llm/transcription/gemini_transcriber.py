import base64
import logging
import time

import httpx

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.http_retry import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    post_with_retries,
)
from vet_soap_notetaker_backend.llm.transcription import Transcriber

logger = logging.getLogger("vet_soap_notetaker_backend.gemini_transcriber")

ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Resumable upload + file-resource endpoints for the Files API fallback.
FILES_UPLOAD_ENDPOINT = "https://generativelanguage.googleapis.com/upload/v1beta/files"
FILE_RESOURCE_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/{name}"

# NOTE: the mobile app records AAC in an .m4a container, so labelling every clip
# "audio/wav" is technically wrong -- fixing that means threading the real
# Content-Type through the Transcriber interface, tracked as a separate change.
# Kept here for parity between the inline and Files API paths.
AUDIO_MIME = "audio/wav"

# Inline requests are capped at 100 MB by Gemini; we switch to the Files API
# before that, leaving ~20 MB of head-room. The threshold is measured on the
# base64-encoded size, since that is what actually travels in the request body.
INLINE_MAX_BYTES = 80 * 1024 * 1024
# Transcribing a large (tens-of-minutes) clip can take well over the inline
# 120s timeout, so the Files API path waits longer.
FILES_API_TIMEOUT_SECONDS = 300.0

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


def _estimated_base64_len(num_bytes: int) -> int:
    # base64 encodes every 3 input bytes as 4 output chars (rounded up).
    return (num_bytes + 2) // 3 * 4


class GeminiTranscriber(Transcriber):
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        inline_max_bytes: int = INLINE_MAX_BYTES,
        files_api_timeout_seconds: float = FILES_API_TIMEOUT_SECONDS,
        file_active_poll_interval_seconds: float = 1.0,
        file_active_timeout_seconds: float = 120.0,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.inline_max_bytes = inline_max_bytes
        self.files_api_timeout_seconds = files_api_timeout_seconds
        self.file_active_poll_interval_seconds = file_active_poll_interval_seconds
        self.file_active_timeout_seconds = file_active_timeout_seconds

    @classmethod
    def from_config(cls, config: BackendConfig) -> "GeminiTranscriber":
        return cls(api_key=config.gemini_api_key, model=config.gemini_transcription_model)

    def transcribe(self, audio_bytes: bytes) -> str:
        # Small clips go inline; anything that would overflow the inline request
        # cap is uploaded via the Files API and referenced by URI instead.
        if _estimated_base64_len(len(audio_bytes)) > self.inline_max_bytes:
            logger.info(
                "audio is %d bytes, exceeding the inline ceiling -- using the Files API",
                len(audio_bytes),
            )
            return self._transcribe_via_files_api(audio_bytes)
        return self._transcribe_inline(audio_bytes)

    def _transcribe_inline(self, audio_bytes: bytes) -> str:
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        response = post_with_retries(
            url=ENDPOINT_TEMPLATE.format(model=self.model),
            params={"key": self.api_key},
            json=self._request_body(
                {"inline_data": {"mime_type": AUDIO_MIME, "data": audio_b64}}
            ),
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )
        return self._parse_transcript(response.json())

    def _transcribe_via_files_api(self, audio_bytes: bytes) -> str:
        file_resource = self._upload_file(audio_bytes)
        name = file_resource["name"]
        try:
            file_resource = self._wait_until_active(file_resource)
            response = post_with_retries(
                url=ENDPOINT_TEMPLATE.format(model=self.model),
                params={"key": self.api_key},
                json=self._request_body(
                    {
                        "file_data": {
                            "mime_type": AUDIO_MIME,
                            "file_uri": file_resource["uri"],
                        }
                    }
                ),
                timeout=self.files_api_timeout_seconds,
                max_retries=self.max_retries,
            )
            return self._parse_transcript(response.json())
        finally:
            self._delete_file(name)

    def _upload_file(self, audio_bytes: bytes) -> dict:
        # 1. Start a resumable upload -- the upload URL comes back in a header.
        start = post_with_retries(
            url=FILES_UPLOAD_ENDPOINT,
            params={"key": self.api_key},
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(audio_bytes)),
                "X-Goog-Upload-Header-Content-Type": AUDIO_MIME,
            },
            json={"file": {"display_name": "exam-audio"}},
            timeout=self.files_api_timeout_seconds,
            max_retries=self.max_retries,
        )
        upload_url = start.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise TranscriptionError("Files API did not return an upload URL")

        # 2. Upload the bytes and finalize in one request.
        finalize = post_with_retries(
            url=upload_url,
            headers={
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            content=audio_bytes,
            timeout=self.files_api_timeout_seconds,
            max_retries=self.max_retries,
        )
        return finalize.json()["file"]

    def _wait_until_active(self, file_resource: dict) -> dict:
        # Audio is often ACTIVE already on finalize (zero polls); otherwise poll
        # the file state briefly until it's ready for inference.
        name = file_resource["name"]
        state = file_resource.get("state")
        max_attempts = max(
            1, int(self.file_active_timeout_seconds / self.file_active_poll_interval_seconds)
        )
        attempts = 0
        while state != "ACTIVE":
            if state == "FAILED":
                raise TranscriptionError(
                    f"Gemini failed to process the uploaded audio (file {name})"
                )
            if attempts >= max_attempts:
                raise TranscriptionError(
                    f"uploaded audio did not become ACTIVE within "
                    f"{self.file_active_timeout_seconds}s (file {name})"
                )
            time.sleep(self.file_active_poll_interval_seconds)
            attempts += 1
            response = httpx.get(
                FILE_RESOURCE_ENDPOINT.format(name=name),
                params={"key": self.api_key},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            file_resource = response.json()
            state = file_resource.get("state")
        return file_resource

    def _delete_file(self, name: str) -> None:
        # Best-effort cleanup; uploaded files also auto-expire after 48h, so a
        # failed delete must never fail the transcription.
        try:
            httpx.delete(
                FILE_RESOURCE_ENDPOINT.format(name=name),
                params={"key": self.api_key},
                timeout=self.timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - cleanup is advisory only
            logger.warning("failed to delete uploaded file %s", name, exc_info=True)

    def _request_body(self, audio_part: dict) -> dict:
        return {"contents": [{"parts": [{"text": TRANSCRIPTION_PROMPT}, audio_part]}]}

    def _parse_transcript(self, data: dict) -> str:
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
