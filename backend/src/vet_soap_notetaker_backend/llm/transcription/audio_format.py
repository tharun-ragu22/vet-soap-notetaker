"""Which audio format to tell the transcription provider an upload is in.

The phone records AAC in an .m4a container; the desktop records WAV. Labelling
an m4a as WAV made the provider misread it, so the upload's Content-Type picks
the label. Anything missing or unrecognised is treated as WAV, which is what
the desktop (and older clients) send.
"""

DEFAULT_MIME = "audio/wav"
# The label for AAC-in-m4a uploads.
M4A_MIME = "audio/mp4"

_MIMES = {
    "audio/m4a": M4A_MIME,
    "audio/x-m4a": M4A_MIME,
    "audio/mp4": M4A_MIME,
    "audio/aac": M4A_MIME,
    "audio/wav": DEFAULT_MIME,
    "audio/x-wav": DEFAULT_MIME,
    "audio/wave": DEFAULT_MIME,
    "audio/vnd.wave": DEFAULT_MIME,
}


def transcription_mime(content_type: str | None) -> str:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    return _MIMES.get(media_type, DEFAULT_MIME)
