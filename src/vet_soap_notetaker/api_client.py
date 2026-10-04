import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("vet_soap_notetaker.api_client")


class ApiClientError(Exception):
    pass


@dataclass
class SoapNote:
    subjective: str
    objective: str
    assessment: str
    plan: str
    transcript: str = ""


@dataclass
class Exam:
    """A persisted exam as served by the backend history endpoints — the shared
    record the mobile and desktop apps both read from and edit."""

    id: str
    created_at: str
    subjective: str
    objective: str
    assessment: str
    plan: str
    transcript: str = ""
    patient_name: str | None = None

    @property
    def soap_text(self) -> str:
        # Local import avoids a circular import (pipeline imports api_client).
        from vet_soap_notetaker.pipeline import format_soap_text

        return format_soap_text(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Exam":
        return cls(
            id=data["id"],
            created_at=data["created_at"],
            subjective=data["subjective"],
            objective=data["objective"],
            assessment=data["assessment"],
            plan=data["plan"],
            transcript=data.get("transcript", ""),
            patient_name=data.get("patient_name"),
        )


class ApiClient:
    def __init__(self, endpoint: str, timeout_seconds: float, api_key: str = ""):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key

    def _auth_headers(self, extra: dict) -> dict:
        headers = dict(extra)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _parse_soap_response(self, response) -> SoapNote:
        logger.info("backend responded with status %s", response.status_code)
        if response.status_code != 200:
            raise ApiClientError(f"backend returned {response.status_code}: {response.text}")

        data = response.json()
        try:
            return SoapNote(
                subjective=data["subjective"],
                objective=data["objective"],
                assessment=data["assessment"],
                plan=data["plan"],
                transcript=data.get("transcript", ""),
            )
        except KeyError as exc:
            raise ApiClientError(f"backend response missing field: {exc}") from exc

    def generate_soap_note(self, audio_bytes: bytes) -> SoapNote:
        headers = self._auth_headers({"Content-Type": "audio/wav"})

        logger.info("POST %s (timeout=%ss)", self.endpoint, self.timeout_seconds)
        try:
            response = httpx.post(
                self.endpoint,
                content=audio_bytes,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            logger.error("backend request failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        return self._parse_soap_response(response)

    def fetch_history(self) -> list:
        # Read the shared exam history from the backend (single source of truth
        # across mobile + desktop). Returns newest-first Exam objects.
        url = f"{self._api_base()}/history"
        headers = self._auth_headers({})
        try:
            response = httpx.get(url, headers=headers, timeout=self.timeout_seconds)
        except httpx.RequestError as exc:
            logger.error("fetch history failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        if response.status_code != 200:
            raise ApiClientError(f"backend returned {response.status_code}: {response.text}")
        return [Exam.from_dict(item) for item in response.json().get("exams", [])]

    def update_exam(
        self,
        exam_id: str,
        *,
        subjective: str,
        objective: str,
        assessment: str,
        plan: str,
        transcript: str,
    ) -> Exam:
        # Save the vet's structured edits back to the authoritative record so
        # they sync to every device.
        url = f"{self._api_base()}/exams/{exam_id}"
        headers = self._auth_headers({"Content-Type": "application/json"})
        payload = {
            "subjective": subjective,
            "objective": objective,
            "assessment": assessment,
            "plan": plan,
            "transcript": transcript,
        }
        try:
            response = httpx.put(url, json=payload, headers=headers, timeout=self.timeout_seconds)
        except httpx.RequestError as exc:
            logger.error("update exam failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        if response.status_code != 200:
            raise ApiClientError(f"backend returned {response.status_code}: {response.text}")
        return Exam.from_dict(response.json())

    def delete_exam(self, exam_id: str) -> None:
        # Remove an exam from the shared history so the deletion syncs everywhere.
        url = f"{self._api_base()}/exams/{exam_id}"
        headers = self._auth_headers({})
        try:
            response = httpx.delete(url, headers=headers, timeout=self.timeout_seconds)
        except httpx.RequestError as exc:
            logger.error("delete exam failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        if response.status_code != 200:
            raise ApiClientError(f"backend returned {response.status_code}: {response.text}")

    def _api_base(self) -> str:
        # The configured endpoint is the audio POST URL (".../api/soap"); the
        # injection endpoints live alongside it under ".../api/injections", so
        # drop the trailing path segment. Keeps a single configured URL.
        return self.endpoint.rstrip("/").rsplit("/", 1)[0]

    def fetch_pending_injections(self) -> list:
        # Poll the backend for mobile-originated requests to paste a note into
        # AVImark. Each request carries the exam's current note to inject.
        url = f"{self._api_base()}/injections/pending"
        headers = self._auth_headers({})
        try:
            response = httpx.get(url, headers=headers, timeout=self.timeout_seconds)
        except httpx.RequestError as exc:
            logger.error("fetch pending injections failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        if response.status_code != 200:
            raise ApiClientError(
                f"backend returned {response.status_code}: {response.text}"
            )
        return response.json().get("requests", [])

    def ack_injection(self, request_id: str, outcome: str) -> None:
        # Tell the backend a pending injection request has been handled so it's
        # dropped from the pending list and never re-delivered.
        url = f"{self._api_base()}/injections/{request_id}/ack"
        headers = self._auth_headers({"Content-Type": "application/json"})
        try:
            response = httpx.post(
                url, json={"outcome": outcome}, headers=headers, timeout=self.timeout_seconds
            )
        except httpx.RequestError as exc:
            logger.error("ack injection failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        if response.status_code != 200:
            raise ApiClientError(
                f"backend returned {response.status_code}: {response.text}"
            )

    def regenerate_soap_note(self, transcript: str) -> SoapNote:
        # Ask the backend to re-run only note generation over a hand-corrected
        # transcript. Derived from the same base endpoint the audio POST uses so
        # only one URL needs configuring.
        url = self.endpoint.rstrip("/") + "/regenerate"
        headers = self._auth_headers({"Content-Type": "application/json"})

        logger.info("POST %s (timeout=%ss)", url, self.timeout_seconds)
        try:
            response = httpx.post(
                url,
                json={"transcript": transcript},
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            logger.error("backend regenerate request failed: %s", exc)
            raise ApiClientError(f"request failed: {exc}") from exc

        return self._parse_soap_response(response)
