"""Evaluators for NoteGenerator.generate(), whose output is one SoapNote per animal.

A case's metadata describes the animals it expects. A single-animal case can give its
expectations at the top level ({"must_include": {...}}); a multi-animal case lists them under
"patients", each with an optional "name" (as stated in the transcript; omit for an unnamed
animal), "must_include" (SoapNote field -> substrings that field must contain) and
"must_not_include" (substrings -- another animal's findings -- that must appear nowhere in
this animal's note). Notes are matched to animals by name, then unnamed animals take the
remaining notes in order.
"""

from dataclasses import dataclass

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from vet_soap_notetaker_backend.schemas import SoapNote

SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")

Notes = list[SoapNote]


def expected_patients(metadata: dict | None) -> list[dict]:
    metadata = metadata or {}
    if "patients" in metadata:
        return metadata["patients"]
    if "must_include" in metadata:
        return [{"must_include": metadata["must_include"]}]
    return [{}]


def _match(patients: list[dict], notes: Notes) -> list[SoapNote | None]:
    """The note for each expected animal, in ``patients`` order (None if it has none)."""
    if len(patients) == 1 and len(notes) == 1:
        # One animal, one note: it's that animal's, whatever the model named it.
        return [notes[0]]
    remaining = list(notes)
    matched: list[SoapNote | None] = [None] * len(patients)
    for index, patient in enumerate(patients):
        name = (patient.get("name") or "").lower()
        if not name:
            continue
        for note in remaining:
            if name in (note.patient_name or "").lower():
                matched[index] = note
                remaining.remove(note)
                break
    for index, patient in enumerate(patients):
        if not patient.get("name") and remaining:
            matched[index] = remaining.pop(0)
    return matched


def _text(note: SoapNote) -> str:
    return " ".join(getattr(note, field) for field in SOAP_FIELDS).lower()


@dataclass
class PatientCount(Evaluator[str, Notes, dict]):
    """Fails unless generate() returned exactly one note per animal the case expects."""

    def evaluate(self, ctx: EvaluatorContext[str, Notes, dict]) -> EvaluationReason:
        expected = len(expected_patients(ctx.metadata))
        actual = len(ctx.output)
        return EvaluationReason(
            value=actual == expected, reason=f"expected {expected} note(s), got {actual}"
        )


@dataclass
class HasAllSoapFields(Evaluator[str, Notes, dict]):
    """Fails if there are no notes, or any note has a blank SOAP field."""

    def evaluate(self, ctx: EvaluatorContext[str, Notes, dict]) -> bool:
        return bool(ctx.output) and all(
            getattr(note, field).strip() for note in ctx.output for field in SOAP_FIELDS
        )


@dataclass
class FieldKeywordCoverage(Evaluator[str, Notes, dict]):
    """Fraction of every animal's must_include keywords found (case-insensitively) in the
    matching field of *that animal's* note. An animal with no note scores all misses.
    Cases with no must_include entries trivially score 1.0."""

    def evaluate(self, ctx: EvaluatorContext[str, Notes, dict]) -> float:
        patients = expected_patients(ctx.metadata)
        total = hits = 0
        for patient, note in zip(patients, _match(patients, ctx.output)):
            for field, keywords in (patient.get("must_include") or {}).items():
                value = getattr(note, field).lower() if note is not None else ""
                for keyword in keywords:
                    total += 1
                    hits += keyword.lower() in value
        return hits / total if total else 1.0


@dataclass
class NoCrossContamination(Evaluator[str, Notes, dict]):
    """Fails if any animal's note contains one of its must_not_include terms (another
    animal's findings or medications), in any field."""

    def evaluate(self, ctx: EvaluatorContext[str, Notes, dict]) -> EvaluationReason:
        patients = expected_patients(ctx.metadata)
        leaks = []
        for position, (patient, note) in enumerate(zip(patients, _match(patients, ctx.output)), 1):
            if note is None:
                continue
            text = _text(note)
            label = patient.get("name") or f"animal {position}"
            leaks += [
                f"{label}: {term}" for term in patient.get("must_not_include") or []
                if term.lower() in text
            ]
        return EvaluationReason(
            value=not leaks, reason="; ".join(leaks) or "no animal's note holds another's findings"
        )
