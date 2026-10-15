from vet_soap_notetaker_backend.llm.prompts import SOAP_SYSTEM_PROMPT


def test_prompt_asks_for_a_patients_array_of_soap_notes():
    assert '"patients"' in SOAP_SYSTEM_PROMPT
    for field in ("patient_name", "subjective", "objective", "assessment", "plan"):
        assert f'"{field}"' in SOAP_SYSTEM_PROMPT


def test_prompt_asks_for_one_note_per_animal_examined():
    prompt = SOAP_SYSTEM_PROMPT.lower()
    assert "one entry per animal" in prompt
    # An animal that's only mentioned (not examined or discussed clinically)
    # must not get its own note.
    assert "only mentioned" in prompt


def test_prompt_repeats_shared_content_in_every_note():
    # Each note lands in its own AVImark chart, so it must stand alone.
    assert "repeat" in SOAP_SYSTEM_PROMPT.lower()


def test_prompt_prefers_one_note_when_unsure():
    assert "if unsure" in SOAP_SYSTEM_PROMPT.lower()
