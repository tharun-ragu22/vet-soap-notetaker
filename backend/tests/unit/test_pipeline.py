from vet_soap_notetaker_backend.llm.pipeline import SoapPipeline
from vet_soap_notetaker_backend.schemas import SoapNote


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.received_audio = None
        self.received_mime = None

    def transcribe(self, audio_bytes, mime_type="audio/wav"):
        self.received_audio = audio_bytes
        self.received_mime = mime_type
        return self.text


class FakeNoteGenerator:
    def __init__(self, notes):
        self.notes = notes
        self.received_transcript = None

    def generate(self, transcript):
        self.received_transcript = transcript
        return self.notes


def test_process_transcribes_then_generates_note_from_transcript():
    expected_notes = [
        SoapNote(subjective="s1", objective="o1", assessment="a1", plan="p1", patient_name="Bella"),
        SoapNote(subjective="s2", objective="o2", assessment="a2", plan="p2", patient_name="Max"),
    ]
    transcriber = FakeTranscriber(text="owner reports vomiting")
    note_generator = FakeNoteGenerator(notes=expected_notes)
    pipeline = SoapPipeline(transcriber=transcriber, note_generator=note_generator)

    result = pipeline.process(b"RIFF....audio-bytes....")

    assert transcriber.received_audio == b"RIFF....audio-bytes...."
    assert note_generator.received_transcript == "owner reports vomiting"
    assert result.notes == expected_notes
    assert result.transcript == "owner reports vomiting"


def test_transcribe_returns_only_the_transcript_without_generating_a_note():
    transcriber = FakeTranscriber(text="owner reports vomiting")
    note_generator = FakeNoteGenerator(notes=[SoapNote(subjective="s", objective="o", assessment="a", plan="p")])
    pipeline = SoapPipeline(transcriber=transcriber, note_generator=note_generator)

    transcript = pipeline.transcribe(b"RIFF....audio-bytes....")

    assert transcript == "owner reports vomiting"
    assert transcriber.received_audio == b"RIFF....audio-bytes...."
    # Note generation is not invoked on the transcribe-only path.
    assert note_generator.received_transcript is None


def test_generate_from_transcript_skips_transcription_and_echoes_transcript():
    expected_notes = [
        SoapNote(subjective="s1", objective="o1", assessment="a1", plan="p1", patient_name="Bella"),
        SoapNote(subjective="s2", objective="o2", assessment="a2", plan="p2", patient_name="Max"),
    ]
    transcriber = FakeTranscriber(text="should not be used")
    note_generator = FakeNoteGenerator(notes=expected_notes)
    pipeline = SoapPipeline(transcriber=transcriber, note_generator=note_generator)

    result = pipeline.generate_from_transcript("hand-corrected transcript")

    # Transcription is never invoked on the regenerate path.
    assert transcriber.received_audio is None
    assert note_generator.received_transcript == "hand-corrected transcript"
    assert result.notes == expected_notes
    assert result.transcript == "hand-corrected transcript"


def _pipeline(transcriber):
    return SoapPipeline(
        transcriber=transcriber,
        note_generator=FakeNoteGenerator(notes=[SoapNote(subjective="s", objective="o", assessment="a", plan="p")]),
    )


def test_transcribe_hands_the_audio_format_to_the_transcriber():
    transcriber = FakeTranscriber(text="t")

    _pipeline(transcriber).transcribe(b"m4a", mime_type="audio/mp4")

    assert transcriber.received_mime == "audio/mp4"


def test_process_hands_the_audio_format_to_the_transcriber():
    transcriber = FakeTranscriber(text="t")

    _pipeline(transcriber).process(b"m4a", mime_type="audio/mp4")

    assert transcriber.received_mime == "audio/mp4"


def test_audio_is_treated_as_wav_when_no_format_is_given():
    transcriber = FakeTranscriber(text="t")

    _pipeline(transcriber).transcribe(b"RIFF")

    assert transcriber.received_mime == "audio/wav"
