import io
import math
import random
import wave

import pytest

from vet_soap_notetaker_backend.llm.transcription.silence import is_silent_wav

RATE = 16000


def _wav(samples: list[float], sampwidth: int = 2, channels: int = 1) -> bytes:
    """A WAV of the given samples (-1.0..1.0), repeated on every channel."""
    frames = bytearray()
    for sample in samples:
        for _ in range(channels):
            if sampwidth == 1:
                frames += bytes([int(round(128 + sample * 127))])  # 8-bit WAV is unsigned
            else:
                frames += int(round(sample * 32767)).to_bytes(2, "little", signed=True)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sampwidth)
        out.setframerate(RATE)
        out.writeframes(bytes(frames))
    return buffer.getvalue()


def _dbfs(db: float) -> float:
    return 10 ** (db / 20)


def _sine(peak: float, seconds: float = 1.0) -> list[float]:
    return [peak * math.sin(2 * math.pi * 440 * n / RATE) for n in range(int(RATE * seconds))]


def _noise(peak: float, seconds: float = 1.0) -> list[float]:
    rng = random.Random(0)
    return [rng.uniform(-peak, peak) for _ in range(int(RATE * seconds))]


def test_all_zero_audio_is_silent():
    assert is_silent_wav(_wav([0.0] * RATE)) is True


def test_quiet_room_noise_is_silent():
    assert is_silent_wav(_wav(_noise(_dbfs(-55)))) is True


def test_speech_level_audio_is_not_silent():
    assert is_silent_wav(_wav(_sine(_dbfs(-20)))) is False


@pytest.mark.parametrize(("sampwidth", "channels"), [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_8_and_16_bit_mono_and_stereo_are_all_read(sampwidth, channels):
    assert is_silent_wav(_wav([0.0] * RATE, sampwidth, channels)) is True
    assert is_silent_wav(_wav(_sine(_dbfs(-20)), sampwidth, channels)) is False


@pytest.mark.parametrize(
    "audio",
    [b"", b"RIFF....audio....", b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 64],
)
def test_audio_that_is_not_a_readable_wav_is_never_called_silent(audio):
    # "Can't tell" -- an m4a, or a corrupt upload, goes on to the provider.
    assert is_silent_wav(audio) is None


def _float_wav(samples: list[float], extensible: bool = False) -> bytes:
    """A 32-bit float WAV, as the desktop's recorder (scipy.io.wavfile) writes it,
    or in the WAVE_FORMAT_EXTENSIBLE wrapper soundfile uses."""
    import struct

    data = struct.pack(f"<{len(samples)}f", *samples)
    if extensible:
        float_guid = b"\x03\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        fmt = struct.pack("<HHIIHHHHI", 0xFFFE, 1, RATE, RATE * 4, 4, 32, 22, 32, 0x4) + float_guid
    else:
        # Byte-for-byte scipy's layout: an 18-byte fmt chunk (cbSize 0), then fact.
        fmt = struct.pack("<HHIIHHH", 3, 1, RATE, RATE * 4, 4, 32, 0)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if not extensible:
        body += b"fact" + struct.pack("<II", 4, len(samples))
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.mark.parametrize("extensible", [False, True])
def test_32_bit_float_wavs_are_read(extensible):
    assert is_silent_wav(_float_wav([0.0] * RATE, extensible)) is True
    assert is_silent_wav(_float_wav(_noise(_dbfs(-55)), extensible)) is True
    assert is_silent_wav(_float_wav(_sine(_dbfs(-20)), extensible)) is False

