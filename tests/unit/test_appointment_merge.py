# Mirrors mobile/src/services/appointments/mergeRegenerated.test.ts: both apps
# fold a regenerate into an appointment's animals by the same rules.
from vet_soap_notetaker.api_client import ExamDraft, PatientNote
from vet_soap_notetaker.appointment_merge import merge_regenerated


def _fields(plan):
    return {"subjective": "s", "objective": "o", "assessment": "a", "plan": plan}


def draft(exam_id, patient_name, plan="old"):
    return ExamDraft(id=exam_id, patient_name=patient_name, **_fields(plan))


def regenerated(patient_name, plan="new"):
    return PatientNote(patient_name=patient_name, **_fields(plan))


def test_gives_each_animal_its_regenerated_note_keeping_its_id_matched_by_name():
    merged = merge_regenerated(
        [draft("e1", "Bella"), draft("e2", "Max")],
        [regenerated("Max", "max new"), regenerated("Bella", "bella new")],
    )

    assert merged == [
        ExamDraft(id="e2", patient_name="Max", **_fields("max new")),
        ExamDraft(id="e1", patient_name="Bella", **_fields("bella new")),
    ]


def test_matches_names_ignoring_case_and_surrounding_spaces():
    merged = merge_regenerated([draft("e1", " bella ")], [regenerated("Bella"), regenerated("Max")])

    assert merged[0].id == "e1"
    assert merged[1].id is None


def test_adds_a_newly_detected_animal_without_an_id_so_saving_creates_it():
    merged = merge_regenerated(
        [draft("e1", "Bella")], [regenerated("Bella"), regenerated("Luna", "luna plan")]
    )

    assert merged[1] == ExamDraft(id=None, patient_name="Luna", **_fields("luna plan"))


def test_keeps_an_animal_the_regenerate_no_longer_finds_unchanged():
    merged = merge_regenerated(
        [draft("e1", "Bella"), draft("e2", "Max", "max old")], [regenerated("Bella")]
    )

    assert merged == [
        ExamDraft(id="e1", patient_name="Bella", **_fields("new")),
        ExamDraft(id="e2", patient_name="Max", **_fields("max old")),
    ]


def test_pairs_a_single_leftover_animal_with_a_single_leftover_note():
    # One animal, now named by the AI (or renamed): still the same exam.
    merged = merge_regenerated([draft("e1", None)], [regenerated("Bella")])

    assert merged == [ExamDraft(id="e1", patient_name="Bella", **_fields("new"))]


def test_keeps_a_name_the_vet_typed_over_the_regenerated_one():
    merged = merge_regenerated(
        [draft("e1", "Luna")], [regenerated("Patient 1")], typed_names={0}
    )

    assert merged == [ExamDraft(id="e1", patient_name="Luna", **_fields("new"))]


def test_takes_the_regenerated_name_when_the_vet_renamed_the_pet_in_the_transcript():
    # The transcript now says Daisy where it said Bella: the stored name came
    # from the AI, not the vet, so the regenerate's name replaces it.
    merged = merge_regenerated([draft("e1", "Bella")], [regenerated("Daisy")])

    assert merged == [ExamDraft(id="e1", patient_name="Daisy", **_fields("new"))]


def test_keeps_the_stored_name_when_the_regenerate_has_none():
    merged = merge_regenerated([draft("e1", "Bella")], [regenerated(None)])

    assert merged[0].patient_name == "Bella"


def test_a_name_matched_ignoring_case_keeps_its_spelling():
    merged = merge_regenerated([draft("e1", "BELLA")], [regenerated("Bella")])

    assert merged[0].patient_name == "BELLA"


def test_does_not_pair_leftovers_when_there_are_several():
    merged = merge_regenerated(
        [draft("e1", "Patient 1"), draft("e2", "Patient 2")],
        [regenerated("Bella"), regenerated("Max")],
    )

    assert [(e.id, e.patient_name) for e in merged] == [
        (None, "Bella"),
        (None, "Max"),
        ("e1", "Patient 1"),
        ("e2", "Patient 2"),
    ]


def test_never_matches_two_notes_to_the_same_animal():
    merged = merge_regenerated([draft("e1", "Bella")], [regenerated("Bella"), regenerated("bella")])

    assert [e.id for e in merged] == ["e1", None]
