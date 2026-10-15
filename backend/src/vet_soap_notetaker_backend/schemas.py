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
    # One note per animal in the recording (at least one), in the order discussed.
    notes: list[SoapNote]
    transcript: str

    def to_dict(self) -> dict:
        # The first animal's note stays flat at the top level for clients that
        # read a single note; "patients" carries every animal's.
        return {
            **self.notes[0].to_dict(),
            "transcript": self.transcript,
            "patients": [note.to_dict() for note in self.notes],
        }
