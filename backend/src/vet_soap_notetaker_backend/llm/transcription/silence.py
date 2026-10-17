"""Spot a silent WAV before paying a provider to transcribe it.

Given silence, a transcription model can invent a whole conversation, so a WAV
whose loudest sample is below room-noise level never goes to the provider. Only
WAV can be checked here; the phone's m4a can't be decoded without ffmpeg, so for
that the transcription prompt's NO_SPEECH reply is the guard.

The RIFF chunks are read by hand because the stdlib `wave` module only reads
integer PCM, and the desktop recorder (scipy.io.wavfile) writes 32-bit float.
"""

import array
import math
import struct
import sys

# Quiet-room noise sits around -60..-50 dBFS; speech peaks well above -30.
SILENCE_PEAK_DBFS = -50.0

_PCM = 1
_IEEE_FLOAT = 3
_EXTENSIBLE = 0xFFFE

# (format, bits per sample) -> (array typecode, full scale, offset of silence)
_SAMPLE_TYPES = {
    (_PCM, 8): ("B", 128, 128),  # 8-bit WAV is unsigned, centred on 128
    (_PCM, 16): ("h", 32768, 0),
    (_PCM, 32): ("i", 2147483648, 0),
    (_IEEE_FLOAT, 32): ("f", 1.0, 0),
}


def is_silent_wav(audio_bytes: bytes) -> bool | None:
    """True if the WAV's peak level is below SILENCE_PEAK_DBFS, False if it's
    louder, None when the bytes aren't a WAV this can read."""
    parsed = _read_wav(audio_bytes)
    if parsed is None:
        return None
    (fmt, bits), frames = parsed
    sample_type = _SAMPLE_TYPES.get((fmt, bits))
    if sample_type is None:
        return None
    typecode, full_scale, centre = sample_type
    samples = array.array(typecode)
    if samples.itemsize * 8 != bits:
        return None
    samples.frombytes(frames[: len(frames) // samples.itemsize * samples.itemsize])
    if sys.byteorder == "big" and samples.itemsize > 1:
        samples.byteswap()
    if not samples:
        return True
    # max()/min() run in C: a 30-minute desktop WAV is tens of millions of samples.
    peak = max(max(samples) - centre, centre - min(samples))
    if not peak > 0:  # also catches NaN
        return True
    return 20 * math.log10(peak / full_scale) < SILENCE_PEAK_DBFS


def _read_wav(audio_bytes: bytes):
    """((format, bits per sample), sample bytes), or None if this isn't a WAV."""
    if len(audio_bytes) < 12 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        return None
    sample_format = None
    offset = 12
    while offset + 8 <= len(audio_bytes):
        chunk_id = audio_bytes[offset : offset + 4]
        (size,) = struct.unpack_from("<I", audio_bytes, offset + 4)
        body = memoryview(audio_bytes)[offset + 8 : offset + 8 + size]  # no copy
        if chunk_id == b"fmt " and len(body) >= 16:
            fmt, _, _, _, _, bits = struct.unpack_from("<HHIIHH", body)
            if fmt == _EXTENSIBLE and len(body) >= 26:
                # The real format is the first two bytes of the SubFormat GUID.
                (fmt,) = struct.unpack_from("<H", body, 24)
            sample_format = (fmt, bits)
        elif chunk_id == b"data":
            return (sample_format, body) if sample_format else None
        offset += 8 + size + (size & 1)  # chunks are word-aligned
    return None
