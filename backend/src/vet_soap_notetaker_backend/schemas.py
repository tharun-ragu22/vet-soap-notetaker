from dataclasses import asdict, dataclass


@dataclass
class SoapNote:
    subjective: str
    objective: str
    assessment: str
    plan: str
    # The patient's name if it was stated in the transcript, else None. Lets the
    # History lists (desktop + mobile) label an exam by patient instead of a timestamp.
    patient_name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SoapResult:
    note: SoapNote
    transcript: str

    def to_dict(self) -> dict:
        return {**self.note.to_dict(), "transcript": self.transcript}
