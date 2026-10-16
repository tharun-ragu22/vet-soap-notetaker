from pydantic_evals.evaluators import EvaluatorContext

from vet_soap_notetaker_backend.llm.evals.note_generation.cases import CASES
from vet_soap_notetaker_backend.llm.evals.note_generation.evaluators import (
    FieldKeywordCoverage,
    HasAllSoapFields,
    NoCrossContamination,
    PatientCount,
    expected_patients,
)
from vet_soap_notetaker_backend.schemas import SoapNote


def _note(name=None, subjective="s", objective="o", assessment="a", plan="p"):
    return SoapNote(subjective, objective, assessment, plan, patient_name=name)


def _ctx(output, metadata):
    return EvaluatorContext(
        name="case",
        inputs="transcript",
        metadata=metadata,
        expected_output=None,
        output=output,
        duration=1.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


TWO_DOGS = {
    "patients": [
        {"name": "Bella", "must_include": {"assessment": ["otitis"]},
         "must_not_include": ["carprofen"]},
        {"name": "Max", "must_include": {"plan": ["carprofen"]},
         "must_not_include": ["otitis"]},
    ]
}
BELLA = _note("Bella", assessment="Otitis externa")
MAX = _note("Max", plan="Carprofen for five days")


# --- expected_patients ------------------------------------------------------------


def test_a_case_without_patients_expects_one_animal_with_its_top_level_keywords():
    metadata = {"must_include": {"plan": ["rabies"]}}

    assert expected_patients(metadata) == [{"must_include": {"plan": ["rabies"]}}]
    assert expected_patients(None) == [{}]


def test_a_case_with_patients_expects_each_of_them():
    assert expected_patients(TWO_DOGS) == TWO_DOGS["patients"]


# --- PatientCount --------------------------------------------------------------------


def test_patient_count_passes_only_with_one_note_per_expected_animal():
    assert PatientCount().evaluate(_ctx([BELLA, MAX], TWO_DOGS)).value is True
    one = PatientCount().evaluate(_ctx([BELLA], TWO_DOGS))
    assert one.value is False and "1" in one.reason and "2" in one.reason
    assert PatientCount().evaluate(_ctx([BELLA], {})).value is True
    assert PatientCount().evaluate(_ctx([BELLA, MAX], {})).value is False


# --- HasAllSoapFields ------------------------------------------------------------------


def test_has_all_soap_fields_checks_every_note():
    assert HasAllSoapFields().evaluate(_ctx([BELLA, MAX], TWO_DOGS)) is True
    assert HasAllSoapFields().evaluate(_ctx([BELLA, _note("Max", plan=" ")], TWO_DOGS)) is False
    assert HasAllSoapFields().evaluate(_ctx([], TWO_DOGS)) is False


# --- FieldKeywordCoverage ----------------------------------------------------------------


def test_keyword_coverage_grades_each_animal_against_its_own_note_by_name():
    # Order doesn't matter: notes are matched to animals by name.
    assert FieldKeywordCoverage().evaluate(_ctx([MAX, BELLA], TWO_DOGS)) == 1.0


def test_keyword_coverage_counts_a_missing_animal_as_all_misses():
    assert FieldKeywordCoverage().evaluate(_ctx([BELLA], TWO_DOGS)) == 0.5


def test_keyword_coverage_does_not_credit_keywords_found_in_another_animals_note():
    swapped = [_note("Bella", plan="carprofen"), _note("Max", assessment="otitis")]

    assert FieldKeywordCoverage().evaluate(_ctx(swapped, TWO_DOGS)) == 0.0


def test_unnamed_animals_take_the_notes_left_after_named_ones_are_matched():
    metadata = {"patients": [
        {"must_include": {"plan": ["nail trim"]}},
        {"name": "Duke", "must_include": {"plan": ["rabies"]}},
    ]}
    notes = [_note("Duke", plan="rabies"), _note("Patient 2", plan="nail trim")]

    assert FieldKeywordCoverage().evaluate(_ctx(notes, metadata)) == 1.0


def test_names_match_case_insensitively_and_within_a_longer_name():
    metadata = {"patients": [{"name": "Max", "must_include": {"plan": ["carprofen"]}}]}

    assert FieldKeywordCoverage().evaluate(_ctx([_note("max (dog)", plan="carprofen")], metadata)) == 1.0


def test_a_single_animal_case_grades_the_only_note_whatever_its_name():
    metadata = {"must_include": {"plan": ["rabies"]}}

    assert FieldKeywordCoverage().evaluate(_ctx([_note("Biscuit", plan="Rabies")], metadata)) == 1.0
    assert FieldKeywordCoverage().evaluate(_ctx([_note()], {})) == 1.0


# --- NoCrossContamination -------------------------------------------------------------------


def test_no_cross_contamination_passes_when_each_note_keeps_to_its_animal():
    assert NoCrossContamination().evaluate(_ctx([BELLA, MAX], TWO_DOGS)).value is True


def test_no_cross_contamination_fails_on_another_animals_finding_in_any_field():
    leaked = _note("Bella", assessment="Otitis externa", objective="also on CARPROFEN")

    result = NoCrossContamination().evaluate(_ctx([leaked, MAX], TWO_DOGS))

    assert result.value is False
    assert "Bella" in result.reason and "carprofen" in result.reason


def test_no_cross_contamination_ignores_animals_without_a_note():
    # A missing animal is PatientCount's failure, not contamination.
    assert NoCrossContamination().evaluate(_ctx([BELLA], TWO_DOGS)).value is True


# --- the cases themselves ------------------------------------------------------------------------


def test_multi_animal_cases_name_their_animals_and_what_each_must_not_contain():
    multi = [case for case in CASES if len(expected_patients(case.metadata)) > 1]

    assert len(multi) >= 3
    for case in multi:
        for patient in expected_patients(case.metadata):
            assert patient.get("must_include"), case.name
            assert patient.get("must_not_include"), case.name


def test_there_is_a_case_where_a_pet_is_only_mentioned():
    assert any(case.metadata.get("category") == "pet_mentioned_not_examined" for case in CASES)
