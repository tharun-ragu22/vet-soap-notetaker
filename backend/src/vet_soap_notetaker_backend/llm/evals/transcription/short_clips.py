"""Short and silent eval clips -- the shape of the "made-up transcript" bug.

A silent phone recording came back from Gemini as a whole invented exam
conversation, so besides the long recordings the evals transcribe:

- the first ~20 seconds of each recording, cut after the last turn that finishes
  in time (never mid-word), graded against just those turns; and
- silent clips, which must come back with no speech at all.

Both are made at eval time from the existing audio in both formats the backend
receives: WAV like the desktop, and AAC in .m4a like the phone (encoded with
PyAV, which bundles ffmpeg). Nothing new goes into the eval-audio release.
"""

import io
import wave
from pathlib import Path

import av

RATE = 16000  # the desktop records 16 kHz mono
PHONE_RATE = 44100  # expo-audio's HIGH_QUALITY preset
SHORT_CLIP_SECONDS = 20
SILENT_CLIP_SECONDS = (10, 30)


def clip_end(segments: list[dict], seconds: float) -> float:
    """Where a clip of at most `seconds` should end: after the last turn that
    finishes in time, so no turn is cut off. 0.0 if none does."""
    ends = [s["end"] for s in segments if s.get("kind") == "turn" and s["end"] <= seconds]
    return max(ends, default=0.0)


def short_reference(segments: list[dict], seconds: float) -> str:
    """The reference transcript for that clip: the turns that finish in time."""
    return "".join(
        f"{s['speaker']}: {s['text']}\n"
        for s in segments
        if s.get("kind") == "turn" and s["end"] <= seconds
    )


def silent_wav(seconds: float) -> bytes:
    return _wav(b"\x00\x00" * int(seconds * RATE))


def silent_m4a(seconds: float) -> bytes:
    return _m4a(b"\x00\x00" * int(seconds * RATE))


def cut(audio_path: Path, end_seconds: float) -> tuple[bytes, bytes]:
    """The first `end_seconds` of a recording, as (WAV, m4a)."""
    pcm = _pcm16(audio_path, end_seconds)
    return _wav(pcm), _m4a(pcm)


def _pcm16(audio_path: Path, end_seconds: float) -> bytes:
    """Decode the start of any recording to 16-bit mono PCM at RATE."""
    needed = int(end_seconds * RATE) * 2
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    pcm = bytearray()
    with av.open(str(audio_path)) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pcm += bytes(out.planes[0])[: out.samples * 2]
            if len(pcm) >= needed:
                break
    return bytes(pcm[:needed])


def _wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


def _m4a(pcm: bytes) -> bytes:
    """AAC in an .m4a container, at the phone's sample rate."""
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="ipod") as container:
        stream = container.add_stream("aac", rate=PHONE_RATE, layout="mono")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=PHONE_RATE)
        chunk = 1024 * 2
        for start in range(0, len(pcm), chunk):
            block = pcm[start : start + chunk]
            frame = av.AudioFrame(format="s16", layout="mono", samples=len(block) // 2)
            frame.planes[0].update(block)
            frame.sample_rate = RATE
            for resampled in resampler.resample(frame):
                container.mux(stream.encode(resampled))
        for resampled in resampler.resample(None):
            container.mux(stream.encode(resampled))
        container.mux(stream.encode(None))
    return buffer.getvalue()
