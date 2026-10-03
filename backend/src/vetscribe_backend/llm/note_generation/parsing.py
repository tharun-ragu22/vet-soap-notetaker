import json

from vetscribe_backend.schemas import SoapNote


class NoteParsingError(Exception):
    pass


def parse_soap_json(raw_text: str) -> SoapNote:
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

    try:
        return SoapNote(
            subjective=data["subjective"],
            objective=data["objective"],
            assessment=data["assessment"],
            plan=data["plan"],
            # Optional: models that omit it (or emit null) leave the exam unlabelled.
            patient_name=data.get("patient_name") or None,
        )
    except KeyError as exc:
        raise NoteParsingError(f"model response missing field: {exc}") from exc
