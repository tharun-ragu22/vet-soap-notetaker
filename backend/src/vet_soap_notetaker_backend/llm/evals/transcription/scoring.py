"""Scoring for the transcription evals: compare a transcript with what was actually said.

Pure functions, no I/O. Text is normalized first so that formatting choices that don't
change meaning ("16 mg" vs "16 milligrams", "4/6" vs "4 out of 6", "Dr." vs "Doctor",
speaker labels, punctuation, case) never count as transcription errors.
"""

import difflib
import re

# A speaker label at the start of a line: "Veterinarian:", "Owner:", "Speaker 2:", ...
_LABEL = re.compile(
    r"^\s*(?:veterinarian|vet|doctor|owner|client|technician|tech|speaker\s*\d+)"
    r"(?:\s*\([^)]*\))?\s*:\s*",
    re.IGNORECASE | re.MULTILINE,
)
# Normalized spellings, applied word by word after splitting.
_EQUIVALENT = {
    "mg": "milligram", "milligrams": "milligram",
    "kg": "kilogram", "kgs": "kilogram", "kilograms": "kilogram", "kilo": "kilogram", "kilos": "kilogram",
    "ml": "milliliter", "mls": "milliliter", "milliliters": "milliliter",
    "millilitre": "milliliter", "millilitres": "milliliter",
    "lb": "pound", "lbs": "pound", "pounds": "pound",
    "cm": "centimeter", "centimeters": "centimeter",
    "dr": "doctor",
    "okay": "ok",
}


def normalize_words(text: str) -> list[str]:
    text = _LABEL.sub(" ", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)                 # 2,000 -> 2000
    text = re.sub(r"\$(\d+(?:\.\d+)?)", r"\1 dollars", text)        # $650 -> 650 dollars
    text = re.sub(r"(\d)\s*/\s*(\d)", r"\1 out of \2", text)        # 4/6 -> 4 out of 6
    text = re.sub(r"(\d)\s*\+", r"\1 plus", text)                   # 3+ -> 3 plus
    text = re.sub(r"(\d)\s*%", r"\1 percent", text)                 # 15% -> 15 percent
    text = text.lower()
    # Keep word characters, apostrophes inside words and decimal points inside numbers.
    words = re.findall(r"\d+(?:\.\d+)?|[a-z0-9]+(?:'[a-z]+)*", text)
    return [_EQUIVALENT.get(w, w) for w in words]


def word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    """(substitutions + deletions + insertions) / reference length -- word-level Levenshtein."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    previous = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, 1):
        current = [i]
        for j, hyp_word in enumerate(hypothesis, 1):
            current.append(min(
                previous[j] + 1,                            # deletion
                current[j - 1] + 1,                         # insertion
                previous[j - 1] + (ref_word != hyp_word),   # substitution / match
            ))
        previous = current
    return previous[-1] / len(reference)


def term_recall(terms, transcript: str) -> tuple[list[str], list[str]]:
    """Which clinical terms made it into the transcript. Each term is a tuple of
    acceptable spellings; it's reported by its first one. Whole words only."""
    haystack = f" {' '.join(normalize_words(transcript))} "
    found, missing = [], []
    for variants in terms:
        hit = any(f" {' '.join(normalize_words(v))} " in haystack for v in variants)
        (found if hit else missing).append(variants[0])
    return found, missing


def window_recall(segments: list[dict], hypothesis: list[str], window_s: float = 300) -> list[tuple[int, float]]:
    """Share of the reference words that appear (in order) in the transcript, per
    ``window_s`` of audio. Each word's time is interpolated within its turn. Catches a
    transcript that degrades or stops partway through a long recording. Returns
    (window start in seconds, recall) for every window that contains speech."""
    reference, times = [], []
    for segment in segments:
        if segment["kind"] != "turn":
            continue
        words = normalize_words(segment["text"])
        span = segment["end"] - segment["start"]
        for k, word in enumerate(words):
            reference.append(word)
            times.append(segment["start"] + span * k / max(len(words), 1))

    matched = [False] * len(reference)
    matcher = difflib.SequenceMatcher(None, reference, hypothesis, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.a, block.a + block.size):
            matched[k] = True

    totals: dict[int, list[int]] = {}
    for when, hit in zip(times, matched):
        start = int(when // window_s * window_s)
        heard, total = totals.setdefault(start, [0, 0])
        totals[start] = [heard + hit, total + 1]
    return [(start, heard / total) for start, (heard, total) in sorted(totals.items())]


def speaker_label_rate(transcript: str) -> float:
    """Share of non-blank lines that start with a speaker label."""
    lines = [line for line in transcript.splitlines() if line.strip()]
    if not lines:
        return 0.0
    return sum(1 for line in lines if _LABEL.match(line)) / len(lines)

