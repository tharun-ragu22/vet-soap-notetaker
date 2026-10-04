import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from vet_soap_notetaker_backend.schemas import SoapNote


@dataclass
class Exam:
    """A persisted exam: the generated SOAP note plus its transcript and metadata."""

    id: str
    created_at: str
    subjective: str
    objective: str
    assessment: str
    plan: str
    transcript: str
    patient_name: str | None = None

    def to_dict(self) -> dict:
        # Key order matches the JSON shape the mobile/desktop clients parse.
        return {
            "id": self.id,
            "created_at": self.created_at,
            "patient_name": self.patient_name,
            "subjective": self.subjective,
            "objective": self.objective,
            "assessment": self.assessment,
            "plan": self.plan,
            "transcript": self.transcript,
        }


class ExamStore:
    """In-memory, thread-safe store of exams — the backend's record of every note
    generated across mobile and desktop sessions, so both can sync from one source.

    The id/clock factories are injectable so tests are deterministic. Subclasses add
    durability by overriding ``_persist`` (see :class:`JsonFileExamStore`)."""

    def __init__(
        self,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ):
        self._exams: dict[str, Exam] = {}
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.Lock()

    def add(self, note: SoapNote, transcript: str, patient_name: str | None = None) -> Exam:
        with self._lock:
            exam = Exam(
                id=self._id_factory(),
                created_at=self._clock(),
                subjective=note.subjective,
                objective=note.objective,
                assessment=note.assessment,
                plan=note.plan,
                transcript=transcript,
                patient_name=patient_name,
            )
            self._exams[exam.id] = exam
            self._persist()
            return exam

    def get(self, exam_id: str) -> Exam | None:
        with self._lock:
            return self._exams.get(exam_id)

    def list(self) -> list[Exam]:
        # Newest first (insertion order is chronological; reverse it).
        with self._lock:
            return list(reversed(self._exams.values()))

    def update(
        self,
        exam_id: str,
        *,
        subjective: str,
        objective: str,
        assessment: str,
        plan: str,
        transcript: str,
        patient_name: str | None = None,
    ) -> Exam | None:
        with self._lock:
            existing = self._exams.get(exam_id)
            if existing is None:
                return None
            updated = Exam(
                id=existing.id,
                created_at=existing.created_at,
                subjective=subjective,
                objective=objective,
                assessment=assessment,
                plan=plan,
                transcript=transcript,
                patient_name=patient_name if patient_name is not None else existing.patient_name,
            )
            self._exams[exam_id] = updated
            self._persist()
            return updated

    def delete(self, exam_id: str) -> bool:
        with self._lock:
            if exam_id not in self._exams:
                return False
            del self._exams[exam_id]
            self._persist()
            return True

    def _persist(self) -> None:  # pragma: no cover - no-op for the in-memory store
        """Hook called under the lock after every mutation. In-memory: nothing to do."""


class JsonFileExamStore(ExamStore):
    """ExamStore that durably persists to a JSON file so records survive restarts."""

    def __init__(
        self,
        path: Path | str,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ):
        super().__init__(id_factory=id_factory, clock=clock)
        self._path = Path(path)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text() or "[]")
        for item in raw:
            exam = Exam(**item)
            self._exams[exam.id] = exam

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Store chronologically; list() handles newest-first at read time.
        payload = [asdict(exam) for exam in self._exams.values()]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)
