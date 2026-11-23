import json
import logging
from pathlib import Path

from vet_soap_notetaker.api_client import Appointment, ApiClientError, BackendUnreachableError
from vet_soap_notetaker.appointment_store import IAppointmentStore
from vet_soap_notetaker.paths import get_appdata_base_dir

logger = logging.getLogger("vet_soap_notetaker.backend_history_store")


def get_cache_path() -> Path:
    # Local mirror of the backend's appointments, under the same data root as
    # the rest of Vet Soap Notetaker's files, so History still shows the
    # last-known list when the backend is briefly unreachable. A new name: the
    # old exam-by-exam history_cache.json is simply left unread.
    return get_appdata_base_dir() / "appointments_cache.json"


class BackendHistoryStore(IAppointmentStore):
    """Backs the desktop History window with the backend's appointments -- the
    single source of truth mobile and desktop both read -- while keeping a local
    cache so a momentary backend outage doesn't blank the window.

    Each call goes to the backend via the injected ``ApiClient`` and mirrors the
    result into the cache."""

    def __init__(self, api_client, cache_path=None):
        self.api_client = api_client
        self.cache_path = Path(cache_path) if cache_path else get_cache_path()

    def list_appointments(self):
        try:
            appointments = self.api_client.list_appointments()
        except ApiClientError as exc:
            logger.warning("history fetch failed, serving cache: %s", exc)
            return self._read_cache()
        self._write_cache(appointments)
        return appointments

    def save_appointment(self, appointment_id, *, transcript, exams):
        try:
            saved = self.api_client.save_appointment(
                appointment_id, transcript=transcript, exams=exams
            )
        except BackendUnreachableError as exc:
            logger.warning("appointment save failed (backend unreachable): %s", exc)
            return None
        self._replace_in_cache(saved)
        return saved

    def delete_appointment(self, appointment_id):
        try:
            self.api_client.delete_appointment(appointment_id)
        except ApiClientError as exc:
            logger.warning("appointment delete failed: %s", exc)
            return False
        self._write_cache([a for a in self._read_cache() if a.id != appointment_id])
        return True

    def retry(self, appointment_id):
        return self._replace_in_cache(self.api_client.retry_appointment(appointment_id))

    def complete_notes(self, appointment_id):
        return self._replace_in_cache(
            self.api_client.complete_appointment_notes(appointment_id)
        )

    # --- local cache ------------------------------------------------------

    def _read_cache(self):
        if not self.cache_path.exists():
            return []
        try:
            raw = json.loads(self.cache_path.read_text() or "[]")
            return [Appointment.from_dict(item) for item in raw]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("unreadable history cache %s: %s", self.cache_path, exc)
            return []

    def _write_cache(self, appointments):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [self._to_dict(a) for a in appointments]
            tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.cache_path)
        except OSError as exc:
            # The cache is best-effort; a write failure must not break History.
            logger.warning("failed to write history cache %s: %s", self.cache_path, exc)

    def _replace_in_cache(self, appointment):
        cached = self._read_cache()
        if any(a.id == appointment.id for a in cached):
            cached = [appointment if a.id == appointment.id else a for a in cached]
        else:
            cached.insert(0, appointment)
        self._write_cache(cached)
        return appointment

    @staticmethod
    def _to_dict(appointment):
        # The backend's own shape, so Appointment.from_dict reads it back.
        return {
            "id": appointment.id,
            "created_at": appointment.created_at,
            "transcript": appointment.transcript,
            "status": appointment.status,
            "exams": [
                {
                    "id": exam.id,
                    "appointment_id": exam.appointment_id,
                    "created_at": exam.created_at,
                    "patient_name": exam.patient_name,
                    "subjective": exam.subjective,
                    "objective": exam.objective,
                    "assessment": exam.assessment,
                    "plan": exam.plan,
                    "note_pending": exam.note_pending,
                }
                for exam in appointment.exams
            ],
        }
