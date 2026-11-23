"""Fold a regenerate's notes into an appointment's animals.

A Python port of the mobile app's ``mergeRegenerated``
(``mobile/src/services/appointments/mergeRegenerated.ts``): both apps must give
each animal the same note for the same regenerate.
"""

from vet_soap_notetaker.api_client import ExamDraft


def _key(name):
    return (name or "").strip().lower()


def merge_regenerated(current, regenerated):
    """The appointment's animals after a regenerate, as an unsaved draft.

    Each regenerated note replaces the note of the animal with the same name
    (ignoring case), keeping that exam's id so saving updates it rather than
    creating a duplicate. If exactly one animal and one note are left
    unmatched, they're the same animal (the AI named it, or the vet renamed
    it). Notes still unmatched are new animals (no id, so saving creates them);
    animals still unmatched are kept unchanged -- the vet deletes one
    deliberately, never as a side effect. A name the vet gave an animal is kept
    over the regenerated one.
    """
    unmatched = list(current)
    matches = []
    for note in regenerated:
        name = _key(note.patient_name)
        match = None
        if name:
            for index, exam in enumerate(unmatched):
                if _key(exam.patient_name) == name:
                    match = unmatched.pop(index)
                    break
        matches.append(match)

    if matches.count(None) == 1 and len(unmatched) == 1:
        matches[matches.index(None)] = unmatched.pop()

    merged = [
        ExamDraft(
            id=exam.id if exam else None,
            patient_name=(exam.patient_name if exam else None) or note.patient_name,
            subjective=note.subjective,
            objective=note.objective,
            assessment=note.assessment,
            plan=note.plan,
        )
        for note, exam in zip(regenerated, matches)
    ]
    return merged + unmatched
