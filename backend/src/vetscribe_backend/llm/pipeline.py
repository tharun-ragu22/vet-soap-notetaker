from vetscribe_backend.llm.note_generation import NoteGenerator
from vetscribe_backend.schemas import SoapResult
from vetscribe_backend.llm.transcription import Transcriber


class SoapPipeline:
    def __init__(self, transcriber: Transcriber, note_generator: NoteGenerator):
        self.transcriber = transcriber
        self.note_generator = note_generator

    def process(self, audio_bytes: bytes) -> SoapResult:
        transcript = self.transcriber.transcribe(audio_bytes)
        note = self.note_generator.generate(transcript)
        return SoapResult(note=note, transcript=transcript)

    def generate_from_transcript(self, transcript: str) -> SoapResult:
        # Skip transcription and re-run only note generation. Used when the vet
        # has corrected the transcript by hand and wants a fresh note from it.
        note = self.note_generator.generate(transcript)
        return SoapResult(note=note, transcript=transcript)
