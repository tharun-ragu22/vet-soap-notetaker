import io
import math
import wave

import av
import pytest

from vet_soap_notetaker_backend.llm.evals.transcription.short_clips import (
    clip_end,
    cut,
    short_reference,
    silent_m4a,
    silent_wav,
)
from vet_soap_notetaker_backend.llm.transcription.silence import is_silent_wav

SEGMENTS = [
    {"kind": "turn", "speaker": "Veterinarian", "start": 0.0, "end": 4.5, "text": "Hi, this must be Murphy."},
    {"kind": "pause", "start": 4.5, "end": 6.0},
    {"kind": "turn", "speaker": "Owner", "start": 6.0, "end": 12.0, "text": "Yes, he's been shaking his head."},
    {"kind": "turn", "speaker": "Veterinarian", "start": 12.5, "end": 25.0, "text": "Let's take a look."},
]


def _duration(audio: bytes) -> float:
    with av.open(io.BytesIO(audio)) as container:
        stream = container.streams.audio[0]
        samples = sum(frame.samples for frame in container.decode(stream))
        return samples / stream.rate


def test_a_short_clip_ends_after_the_last_turn_that_finishes_in_time():
    # Never mid-turn: a cut-off word would count as a transcription error.
    assert clip_end(SEGMENTS, 20) == pytest.approx(12.0)


def test_a_short_clip_has_no_end_when_no_turn_finishes_in_time():
    assert clip_end(SEGMENTS, 0) == 0.0


def test_the_short_reference_holds_only_the_turns_that_finish_in_time():
    assert short_reference(SEGMENTS, 20) == (
        "Veterinarian: Hi, this must be Murphy.\nOwner: Yes, he's been shaking his head.\n"
    )
    assert short_reference(SEGMENTS, 0) == ""


def test_a_silent_wav_is_silent_and_the_right_length():
    audio = silent_wav(10)

    assert is_silent_wav(audio) is True
    with wave.open(io.BytesIO(audio)) as recording:
        assert recording.getnframes() / recording.getframerate() == pytest.approx(10)


def test_a_silent_m4a_is_aac_audio_of_the_right_length():
    audio = silent_m4a(10)

    with av.open(io.BytesIO(audio)) as container:
        assert container.streams.audio[0].codec_context.name == "aac"
    assert _duration(audio) == pytest.approx(10, abs=0.1)


def test_cut_gives_the_start_of_a_recording_as_both_wav_and_m4a(tmp_path):
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(
            int(8000 * math.sin(2 * math.pi * 440 * n / 16000)).to_bytes(2, "little", signed=True)
            for n in range(16000 * 5)
        ))

    wav_bytes, m4a_bytes = cut(source, 2.0)

    assert is_silent_wav(wav_bytes) is False
    assert _duration(wav_bytes) == pytest.approx(2.0, abs=0.01)
    assert _duration(m4a_bytes) == pytest.approx(2.0, abs=0.1)
