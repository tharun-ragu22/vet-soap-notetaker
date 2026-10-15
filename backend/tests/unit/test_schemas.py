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


def test_soap_result_to_dict_flattens_the_first_note_and_lists_every_patient():
    # The flat fields keep single-note clients (the desktop's regenerate, the
    # current mobile app) working; "patients" carries every animal's note.
    bella = SoapNote(subjective="s1", objective="o1", assessment="a1", plan="p1", patient_name="Bella")
    max_ = SoapNote(subjective="s2", objective="o2", assessment="a2", plan="p2", patient_name="Max")
    result = SoapResult(notes=[bella, max_], transcript="owner reports vomiting")

    assert result.to_dict() == {
        "subjective": "s1",
        "objective": "o1",
        "assessment": "a1",
        "plan": "p1",
        "patient_name": "Bella",
        "transcript": "owner reports vomiting",
        "patients": [bella.to_dict(), max_.to_dict()],
    }
