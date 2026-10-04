import json
import logging
from pathlib import Path

from vet_soap_notetaker.api_client import ApiClientError, Exam
from vet_soap_notetaker.paths import get_appdata_base_dir

logger = logging.getLogger("vet_soap_notetaker.backend_history_store")


def get_cache_path() -> Path:
    # Local mirror of the backend's shared history, under the same data root as
    # the rest of Vet Soap Notetaker's files, so History still shows the last-known list
    # when the backend is briefly unreachable.
    return get_appdata_base_dir() / "history_cache.json"


class BackendHistoryStore:
    """Backs the desktop History window with the backend's shared exam store —
    the single source of truth mobile and desktop both read — while keeping a
    local cache so a momentary backend outage doesn't blank the window.

    Presents the same ``list_entries``/``update``/``delete`` surface the History
    window and ``main.py`` already consume; each call goes to the backend via the
    injected ``ApiClient`` and mirrors the result into the cache."""

    def __init__(self, api_client, cache_path=None):
        self.api_client = api_client
        self.cache_path = Path(cache_path) if cache_path else get_cache_path()

    def list_entries(self):
        try:
            exams = self.api_client.fetch_history()
        except ApiClientError as exc:
            logger.warning("history fetch failed, serving cache: %s", exc)
            return self._read_cache()
        self._write_cache(exams)
        return exams

    def update(self, entry_id, *, subjective, objective, assessment, plan, transcript):
        try:
            updated = self.api_client.update_exam(
                entry_id,
                subjective=subjective,
                objective=objective,
                assessment=assessment,
                plan=plan,
                transcript=transcript,
            )
        except ApiClientError as exc:
            logger.warning("history update failed (backend unreachable): %s", exc)
            return None
        self._replace_in_cache(updated)
        return updated

    def delete(self, entry_id):
        try:
            self.api_client.delete_exam(entry_id)
        except ApiClientError as exc:
            logger.warning("history delete failed (backend unreachable): %s", exc)
            return False
        self._drop_from_cache(entry_id)
        return True

    # --- local cache ------------------------------------------------------

    def _read_cache(self):
        if not self.cache_path.exists():
            return []
        try:
            raw = json.loads(self.cache_path.read_text() or "[]")
            return [Exam.from_dict(item) for item in raw]
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("unreadable history cache %s: %s", self.cache_path, exc)
            return []

    def _write_cache(self, exams):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [self._to_dict(e) for e in exams]
            tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.cache_path)
        except OSError as exc:
            # The cache is best-effort; a write failure must not break History.
            logger.warning("failed to write history cache %s: %s", self.cache_path, exc)

    def _replace_in_cache(self, exam):
        cached = self._read_cache()
        cached = [exam if e.id == exam.id else e for e in cached]
        if all(e.id != exam.id for e in cached):
            cached.insert(0, exam)
        self._write_cache(cached)

    def _drop_from_cache(self, entry_id):
        self._write_cache([e for e in self._read_cache() if e.id != entry_id])

    @staticmethod
    def _to_dict(exam):
        return {
            "id": exam.id,
            "created_at": exam.created_at,
            "patient_name": exam.patient_name,
            "subjective": exam.subjective,
            "objective": exam.objective,
            "assessment": exam.assessment,
            "plan": exam.plan,
            "transcript": exam.transcript,
        }
