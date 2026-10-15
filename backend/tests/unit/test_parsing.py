import json

import pytest

from vet_soap_notetaker_backend.llm.note_generation.parsing import (
    NoteParsingError,
    parse_soap_notes,
)


def _patient(name=None, **fields):
    return {
        "patient_name": name,
        "subjective": fields.get("subjective", "s"),
        "objective": fields.get("objective", "o"),
        "assessment": fields.get("assessment", "a"),
        "plan": fields.get("plan", "p"),
    }


def _reply(*patients):
    return json.dumps({"patients": list(patients)})


def test_parses_one_note_per_patient_in_order():
    notes = parse_soap_notes(
        _reply(_patient("Bella", plan="bella plan"), _patient("Max", plan="max plan"))
    )

    assert [n.patient_name for n in notes] == ["Bella", "Max"]
    assert [n.plan for n in notes] == ["bella plan", "max plan"]


def test_parses_a_single_patient():
    notes = parse_soap_notes(_reply(_patient("Bella")))

    assert len(notes) == 1
    assert notes[0].subjective == "s"
    assert notes[0].objective == "o"
    assert notes[0].assessment == "a"
    assert notes[0].plan == "p"


def test_strips_markdown_code_fences():
    notes = parse_soap_notes(f"```json\n{_reply(_patient('Bella'))}\n```")

    assert notes[0].patient_name == "Bella"


def test_accepts_a_bare_single_note_object():
    # A model that ignores the "patients" wrapper and answers with one note is
    # still a usable single-animal note, not a failure.
    notes = parse_soap_notes(json.dumps(_patient("Bella")))

    assert len(notes) == 1
    assert notes[0].patient_name == "Bella"


def test_a_lone_unnamed_patient_stays_unnamed():
    # One animal with no name: History labels the exam by date, as before.
    notes = parse_soap_notes(_reply(_patient(None)))

    assert notes[0].patient_name is None


def test_unnamed_patients_among_several_are_labelled_by_position():
    notes = parse_soap_notes(_reply(_patient("Bella"), _patient(None), _patient("  ")))

    assert [n.patient_name for n in notes] == ["Bella", "Patient 2", "Patient 3"]


def test_patient_names_are_trimmed():
    notes = parse_soap_notes(_reply(_patient("  Bella ")))

    assert notes[0].patient_name == "Bella"


def test_a_missing_patient_name_counts_as_unnamed():
    entry = _patient("Bella")
    del entry["patient_name"]

    notes = parse_soap_notes(_reply(entry))

    assert notes[0].patient_name is None


def test_raises_on_invalid_json():
    with pytest.raises(NoteParsingError):
        parse_soap_notes("not json")


def test_raises_when_patients_is_empty():
    with pytest.raises(NoteParsingError, match="no patients"):
        parse_soap_notes(json.dumps({"patients": []}))


def test_raises_when_patients_is_not_a_list():
    with pytest.raises(NoteParsingError):
        parse_soap_notes(json.dumps({"patients": "Bella"}))


def test_raises_when_the_reply_is_not_an_object():
    with pytest.raises(NoteParsingError):
        parse_soap_notes(json.dumps(["Bella"]))


def test_raises_when_a_patient_entry_is_not_an_object():
    with pytest.raises(NoteParsingError):
        parse_soap_notes(json.dumps({"patients": [_patient("Bella"), "Max"]}))


def test_raises_on_a_missing_field_naming_it():
    entry = _patient("Bella")
    del entry["objective"]

    with pytest.raises(NoteParsingError, match="objective"):
        parse_soap_notes(_reply(entry))


def test_raises_when_a_field_is_not_a_string():
    with pytest.raises(NoteParsingError, match="plan"):
        parse_soap_notes(_reply(_patient("Bella", plan=["give meds"])))


def test_raises_when_patient_name_is_not_a_string():
    with pytest.raises(NoteParsingError, match="patient_name"):
        parse_soap_notes(_reply(_patient(42)))
