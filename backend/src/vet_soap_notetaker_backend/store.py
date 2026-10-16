from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from vet_soap_notetaker_backend.schemas import SoapNote

_EMPTY_NOTE = SoapNote(subjective="", objective="", assessment="", plan="")


class UnknownExamError(ValueError):
    """An appointment edit named an exam that isn't part of that appointment."""


@dataclass(frozen=True)
class Exam:
    """One animal's SOAP note within an appointment.

    ``transcript`` is the appointment's shared transcript: the store keeps it the
    same on every exam of an appointment, and writes it to disk only once.
    """

    id: str
    appointment_id: str
    created_at: str
    subjective: str
    objective: str
    assessment: str
    plan: str
    transcript: str
    patient_name: str | None = None
    # True when transcription succeeded but note generation did not, so the note
    # fields are empty and awaiting a retry (POST /api/exams/{id}/note).
    note_pending: bool = False

    def to_dict(self, include_transcript: bool = True) -> dict:
        # Key order matches the JSON shape the mobile/desktop clients parse.
        data = {
            "id": self.id,
            "appointment_id": self.appointment_id,
            "created_at": self.created_at,
            "patient_name": self.patient_name,
            "subjective": self.subjective,
            "objective": self.objective,
            "assessment": self.assessment,
            "plan": self.plan,
            "transcript": self.transcript,
            "note_pending": self.note_pending,
        }
        if not include_transcript:
            del data["transcript"]
        return data


@dataclass(frozen=True)
class Appointment:
    """One recording: its transcript, and one exam per animal seen.

    An appointment whose note generation failed holds a single empty,
    note-pending placeholder exam until the note is generated or written by hand.
    """

    id: str
    created_at: str
    transcript: str
    exams: tuple[Exam, ...]

    @property
    def note_pending(self) -> bool:
        return any(exam.note_pending for exam in self.exams)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "transcript": self.transcript,
            "note_pending": self.note_pending,
            "exams": [exam.to_dict(include_transcript=False) for exam in self.exams],
        }


@dataclass(frozen=True)
class ExamEdit:
    """One animal in an appointment edit: an existing exam (``id``) or a new one."""

    subjective: str
    objective: str
    assessment: str
    plan: str
    patient_name: str | None = None
    id: str | None = None


class ExamStore:
    """In-memory, thread-safe store of appointments and their exams -- the
    backend's record of every note generated across mobile and desktop sessions,
    so both can sync from one source.

    Records are immutable snapshots: every write replaces them, so a handler
    holding one outside the lock never sees it change. The id/clock factories are
    injectable so tests are deterministic. Subclasses add durability by
    overriding ``_persist`` (see :class:`JsonFileExamStore`)."""

    def __init__(
        self,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ):
        # Insertion order is chronological.
        self._appointments: dict[str, Appointment] = {}
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.Lock()

    # --- appointments ------------------------------------------------------------

    def add_appointment(self, transcript: str, notes: list[SoapNote]) -> Appointment:
        """A new appointment with one exam per note, in order."""
        with self._lock:
            appointment = self._create_locked(transcript, notes, note_pending=False)
            self._persist()
            return appointment

    def add_pending_appointment(self, transcript: str) -> Appointment:
        """A new appointment whose note generation failed: the transcript is kept,
        with one empty note-pending exam for the retry to fill in."""
        with self._lock:
            appointment = self._create_locked(transcript, [_EMPTY_NOTE], note_pending=True)
            self._persist()
            return appointment

    def get_appointment(self, appointment_id: str) -> Appointment | None:
        with self._lock:
            return self._appointments.get(appointment_id)

    def list_appointments(self) -> list[Appointment]:
        # Newest first.
        with self._lock:
            return list(reversed(self._appointments.values()))

    def update_appointment(
        self, appointment_id: str, *, transcript: str, exams: list[ExamEdit]
    ) -> Appointment | None:
        """Replace the transcript and the set of animals: an edit with an ``id``
        updates that exam, one without adds a new exam, and exams left out are
        deleted. Raises UnknownExamError (changing nothing) for an ``id`` that
        isn't in this appointment; returns None for an unknown appointment."""
        if not exams:
            raise ValueError("an appointment needs at least one exam; delete it instead")
        with self._lock:
            existing = self._appointments.get(appointment_id)
            if existing is None:
                return None
            current = {exam.id: exam for exam in existing.exams}
            unknown = [e.id for e in exams if e.id is not None and e.id not in current]
            if unknown:
                raise UnknownExamError(f"exam not in this appointment: {unknown[0]}")
            ids = [e.id for e in exams if e.id is not None]
            if len(ids) != len(set(ids)):
                raise ValueError("an exam appears more than once")
            updated = []
            for edit in exams:
                fields = dict(
                    subjective=edit.subjective,
                    objective=edit.objective,
                    assessment=edit.assessment,
                    plan=edit.plan,
                    patient_name=edit.patient_name,
                    note_pending=False,
                )
                if edit.id is None:
                    updated.append(self._new_exam(existing.id, transcript, self._clock(), fields))
                else:
                    updated.append(replace(current[edit.id], transcript=transcript, **fields))
            appointment = replace(existing, transcript=transcript, exams=tuple(updated))
            self._appointments[appointment_id] = appointment
            self._persist()
            return appointment

    def delete_appointment(self, appointment_id: str) -> bool:
        with self._lock:
            if self._appointments.pop(appointment_id, None) is None:
                return False
            self._persist()
            return True

    # --- single exams ------------------------------------------------------------

    def add(
        self,
        note: SoapNote,
        transcript: str,
        patient_name: str | None = None,
        note_pending: bool = False,
    ) -> Exam:
        """A new single-animal appointment; returns its exam."""
        with self._lock:
            note = replace(note, patient_name=patient_name)
            appointment = self._create_locked(transcript, [note], note_pending=note_pending)
            self._persist()
            return appointment.exams[0]

    def get(self, exam_id: str) -> Exam | None:
        with self._lock:
            found = self._find_locked(exam_id)
            return found[0].exams[found[1]] if found else None

    def list(self) -> list[Exam]:
        """Every exam: newest appointment first, its animals in recorded order."""
        with self._lock:
            return [
                exam
                for appointment in reversed(self._appointments.values())
                for exam in appointment.exams
            ]

    def update(
        self,
        exam_id: str,
        *,
        subjective: str,
        objective: str,
        assessment: str,
        plan: str,
        transcript: str | None = None,
        patient_name: str | None = None,
    ) -> Exam | None:
        """Save one animal's note. A ``transcript`` replaces the appointment's
        shared transcript, for every animal in it."""
        with self._lock:
            found = self._find_locked(exam_id)
            if found is None:
                return None
            appointment, index = found
            existing = appointment.exams[index]
            updated = replace(
                existing,
                subjective=subjective,
                objective=objective,
                assessment=assessment,
                plan=plan,
                patient_name=patient_name if patient_name is not None else existing.patient_name,
                note_pending=False,
            )
            appointment = self._with_exam(appointment, index, updated)
            if transcript is not None:
                appointment = self._with_transcript(appointment, transcript)
            self._appointments[appointment.id] = appointment
            self._persist()
            return appointment.exams[index]

    def complete_pending(self, exam_id: str, notes: list[SoapNote]) -> Exam | None:
        """Fill in a note-pending exam's note -- but only if it's still pending.

        ``notes`` holds one note per animal in the recording: the first fills in
        this exam, and each further one is added to the same appointment.
        Check-and-write happen under one lock hold, so a note generated for a
        pending exam can never overwrite one the vet saved in the meantime (a hand
        edit clears ``note_pending``), and a retry never adds the further animals
        twice. Returns the exam as it now stands -- completed here, or already
        complete and left untouched -- or None if it no longer exists.
        """
        with self._lock:
            found = self._find_locked(exam_id)
            if found is None:
                return None
            appointment, index = found
            existing = appointment.exams[index]
            if not existing.note_pending:
                return existing
            first, *others = notes
            completed = replace(
                existing,
                subjective=first.subjective,
                objective=first.objective,
                assessment=first.assessment,
                plan=first.plan,
                patient_name=first.patient_name or existing.patient_name,
                note_pending=False,
            )
            appointment = self._with_exam(appointment, index, completed)
            created_at = self._clock()
            added = tuple(
                self._new_exam(appointment.id, appointment.transcript, created_at, _note_fields(n))
                for n in others
            )
            self._appointments[appointment.id] = replace(
                appointment, exams=appointment.exams + added
            )
            self._persist()
            return completed

    def delete(self, exam_id: str) -> bool:
        """Delete one animal's exam; deleting the last one deletes the appointment."""
        with self._lock:
            found = self._find_locked(exam_id)
            if found is None:
                return False
            appointment, index = found
            remaining = appointment.exams[:index] + appointment.exams[index + 1 :]
            if remaining:
                self._appointments[appointment.id] = replace(appointment, exams=remaining)
            else:
                del self._appointments[appointment.id]
            self._persist()
            return True

    # --- internals (call with the lock held) -----------------------------------

    def _create_locked(self, transcript, notes, note_pending) -> Appointment:
        appointment_id = self._id_factory()
        created_at = self._clock()
        exams = tuple(
            self._new_exam(
                appointment_id, transcript, created_at, {**_note_fields(n), "note_pending": note_pending}
            )
            for n in notes
        )
        appointment = Appointment(
            id=appointment_id, created_at=created_at, transcript=transcript, exams=exams
        )
        self._appointments[appointment_id] = appointment
        return appointment

    def _new_exam(self, appointment_id, transcript, created_at, fields) -> Exam:
        return Exam(
            id=self._id_factory(),
            appointment_id=appointment_id,
            created_at=created_at,
            transcript=transcript,
            **fields,
        )

    def _find_locked(self, exam_id) -> tuple[Appointment, int] | None:
        for appointment in self._appointments.values():
            for index, exam in enumerate(appointment.exams):
                if exam.id == exam_id:
                    return appointment, index
        return None

    @staticmethod
    def _with_exam(appointment: Appointment, index: int, exam: Exam) -> Appointment:
        exams = appointment.exams[:index] + (exam,) + appointment.exams[index + 1 :]
        return replace(appointment, exams=exams)

    @staticmethod
    def _with_transcript(appointment: Appointment, transcript: str) -> Appointment:
        return replace(
            appointment,
            transcript=transcript,
            exams=tuple(replace(exam, transcript=transcript) for exam in appointment.exams),
        )

    def _persist(self) -> None:  # pragma: no cover - no-op for the in-memory store
        """Hook called under the lock after every mutation. In-memory: nothing to do."""


def _note_fields(note: SoapNote) -> dict:
    return dict(
        subjective=note.subjective,
        objective=note.objective,
        assessment=note.assessment,
        plan=note.plan,
        patient_name=note.patient_name,
    )


class JsonFileExamStore(ExamStore):
    """ExamStore that durably persists to a JSON file so records survive restarts.

    The file is ``{"appointments": [...]}`` in chronological order, each
    appointment holding its transcript once and its exams without one."""

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
        raw = json.loads(self._path.read_text() or "{}")
        if isinstance(raw, list):
            # Written before appointments existed: a flat list of exams, each
            # with its own transcript. Each becomes a one-animal appointment.
            raw = {"appointments": [_legacy_appointment(item) for item in raw]}
        for item in raw.get("appointments", []):
            exams = tuple(
                Exam(appointment_id=item["id"], transcript=item["transcript"], **exam)
                for exam in item["exams"]
            )
            appointment = Appointment(
                id=item["id"],
                created_at=item["created_at"],
                transcript=item["transcript"],
                exams=exams,
            )
            self._appointments[appointment.id] = appointment

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "appointments": [
                {
                    "id": appointment.id,
                    "created_at": appointment.created_at,
                    "transcript": appointment.transcript,
                    "exams": [_stored_exam(exam) for exam in appointment.exams],
                }
                for appointment in self._appointments.values()
            ]
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)


def _stored_exam(exam: Exam) -> dict:
    data = asdict(exam)
    # Both come from the enclosing appointment.
    del data["appointment_id"], data["transcript"]
    return data


def _legacy_appointment(item: dict) -> dict:
    exam = {k: v for k, v in item.items() if k != "transcript"}
    return {
        "id": f"appt-{item['id']}",
        "created_at": item["created_at"],
        "transcript": item.get("transcript", ""),
        "exams": [exam],
    }
