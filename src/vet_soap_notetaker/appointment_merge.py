"""Fold a regenerate's notes into an appointment's animals.

A Python port of the mobile app's ``mergeRegenerated``
(``mobile/src/services/appointments/mergeRegenerated.ts``): both apps must give
each animal the same note for the same regenerate.
"""

from vet_soap_notetaker.api_client import ExamDraft


def _key(name):
    return (name or "").strip().lower()


def merge_regenerated(current, regenerated, typed_names=frozenset()):
    """The appointment's animals after a regenerate, as an unsaved draft.

    Each regenerated note replaces the note of the animal with the same name
    (ignoring case), keeping that exam's id so saving updates it rather than
    creating a duplicate. If exactly one animal and one note are left
    unmatched, they're the same animal (the AI renamed it, or the vet renamed
    it in the transcript). Notes still unmatched are new animals (no id, so
    saving creates them); animals still unmatched are kept unchanged -- the vet
    deletes one deliberately, never as a side effect.

    Names: ``typed_names`` holds the positions (in ``current``) of animals whose
    name the vet typed into the name field; those are kept. Any other name
    follows the regenerate -- the transcript is what changed -- unless the
    regenerate gives none, or it's the same name in another case.
    """
    unmatched = list(range(len(current)))
    matches = []
    for note in regenerated:
        name = _key(note.patient_name)
        match = None
        if name:
            for position, index in enumerate(unmatched):
                if _key(current[index].patient_name) == name:
                    match = unmatched.pop(position)
                    break
        matches.append(match)

    if matches.count(None) == 1 and len(unmatched) == 1:
        matches[matches.index(None)] = unmatched.pop()

    def name_for(note, index):
        if index is None:
            return note.patient_name
        stored = current[index].patient_name
        if not (stored or "").strip():
            return note.patient_name
        if index in typed_names or not _key(note.patient_name):
            return stored
        if _key(note.patient_name) == _key(stored):
            return stored
        return note.patient_name

    merged = [
        ExamDraft(
            id=current[index].id if index is not None else None,
            patient_name=name_for(note, index),
            subjective=note.subjective,
            objective=note.objective,
            assessment=note.assessment,
            plan=note.plan,
        )
        for note, index in zip(regenerated, matches)
    ]
    return merged + [current[index] for index in unmatched]
