import pytest

from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError, parse_soap_json


def test_parse_soap_json_parses_plain_json():
    note = parse_soap_json(
        '{"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}'
    )
    assert note.subjective == "s"
    assert note.plan == "p"


def test_parse_soap_json_strips_markdown_code_fences():
    note = parse_soap_json(
        '```json\n{"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}\n```'
    )
    assert note.plan == "p"


def test_parse_soap_json_raises_on_invalid_json():
    with pytest.raises(NoteParsingError):
        parse_soap_json("not json")


def test_parse_soap_json_raises_on_missing_field():
    with pytest.raises(NoteParsingError, match="objective"):
        parse_soap_json('{"subjective": "s"}')


def test_parse_soap_json_reads_patient_name_when_present():
    note = parse_soap_json(
        '{"patient_name": "Bella", "subjective": "s", "objective": "o", '
        '"assessment": "a", "plan": "p"}'
    )
    assert note.patient_name == "Bella"


def test_parse_soap_json_defaults_patient_name_to_none_when_absent():
    # Older prompts / providers that omit the field must still parse cleanly.
    note = parse_soap_json(
        '{"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}'
    )
    assert note.patient_name is None


def test_parse_soap_json_treats_json_null_patient_name_as_none():
    note = parse_soap_json(
        '{"patient_name": null, "subjective": "s", "objective": "o", '
        '"assessment": "a", "plan": "p"}'
    )
    assert note.patient_name is None
