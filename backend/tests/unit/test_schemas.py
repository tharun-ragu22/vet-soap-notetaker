from vet_soap_notetaker_backend.schemas import SoapNote, SoapResult


def test_soap_note_to_dict_returns_all_fields():
    note = SoapNote(subjective="s", objective="o", assessment="a", plan="p")
    assert note.to_dict() == {
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "p",
        "patient_name": None,
    }


def test_soap_note_patient_name_defaults_to_none():
    note = SoapNote(subjective="s", objective="o", assessment="a", plan="p")
    assert note.patient_name is None


def test_soap_note_to_dict_includes_patient_name_when_set():
    note = SoapNote(
        subjective="s", objective="o", assessment="a", plan="p", patient_name="Bella"
    )
    assert note.to_dict()["patient_name"] == "Bella"


def test_soap_result_to_dict_includes_note_fields_and_transcript():
    note = SoapNote(subjective="s", objective="o", assessment="a", plan="p")
    result = SoapResult(note=note, transcript="owner reports vomiting")
    assert result.to_dict() == {
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "p",
        "patient_name": None,
        "transcript": "owner reports vomiting",
    }
