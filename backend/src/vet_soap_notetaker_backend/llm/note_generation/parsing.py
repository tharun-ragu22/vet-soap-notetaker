import json

from vet_soap_notetaker_backend.schemas import SoapNote

_SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")


class NoteParsingError(Exception):
    pass


def parse_soap_notes(raw_text: str) -> list[SoapNote]:
    """Parse the model's reply into one SoapNote per patient, in the model's order.

    The reply is ``{"patients": [{patient_name, subjective, objective, assessment,
    plan}, ...]}``. A bare single-note object (a model that dropped the wrapper) is
    accepted as one patient. When there are several patients, unnamed ones are
    labelled "Patient N" by position so each note can be told apart; a lone
    unnamed patient stays unnamed (History labels it by date).
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NoteParsingError(f"model did not return valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NoteParsingError("model response is not a JSON object")

    entries = data["patients"] if "patients" in data else [data]
    if not isinstance(entries, list):
        raise NoteParsingError("model response 'patients' is not a list")
    if not entries:
        raise NoteParsingError("model response has no patients")

    notes = [_parse_patient(entry) for entry in entries]
    if len(notes) > 1:
        for position, note in enumerate(notes, start=1):
            if note.patient_name is None:
                note.patient_name = f"Patient {position}"
    return notes


def _parse_patient(entry) -> SoapNote:
    if not isinstance(entry, dict):
        raise NoteParsingError("model response patient entry is not an object")
    for field in _SOAP_FIELDS:
        if field not in entry:
            raise NoteParsingError(f"model response missing field: {field!r}")
        if not isinstance(entry[field], str):
            raise NoteParsingError(f"model response field {field!r} is not a string")
    name = entry.get("patient_name")
    if name is not None and not isinstance(name, str):
        raise NoteParsingError("model response field 'patient_name' is not a string")
    return SoapNote(
        subjective=entry["subjective"],
        objective=entry["objective"],
        assessment=entry["assessment"],
        plan=entry["plan"],
        # Optional: a blank or missing name leaves the patient unnamed.
        patient_name=(name or "").strip() or None,
    )


def extract_reply_text(response, path):
    """The model's text from a provider's JSON reply, following ``path`` (keys and
    indexes). A reply with no text there -- a refusal, a blocked prompt, an empty
    candidate, a non-JSON body -- is a NoteParsingError, so the backend keeps the
    transcript (202) instead of failing the whole request with a raw 500.
    """
    try:
        value = response.json()
        for step in path:
            value = value[step]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise NoteParsingError(
            f"provider reply had no note text ({type(exc).__name__})"
        ) from exc
    if not isinstance(value, str):
        raise NoteParsingError("provider reply had no note text")
    return value
