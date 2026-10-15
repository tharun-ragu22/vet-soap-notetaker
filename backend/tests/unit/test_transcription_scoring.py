import pytest

from vet_soap_notetaker_backend.llm.evals.transcription.scoring import (
    normalize_words,
    speaker_label_rate,
    term_recall,
    window_recall,
    word_error_rate,
)


def test_normalize_words_drops_speaker_labels_case_and_punctuation():
    text = "Veterinarian: Hi there, I'm Doctor Patel.\nOwner: Yeah -- he's GREAT!"
    assert normalize_words(text) == ["hi", "there", "i'm", "doctor", "patel", "yeah", "he's", "great"]


def test_normalize_words_drops_generic_speaker_labels():
    assert normalize_words("Speaker 1: hello\nSpeaker 2: hi") == ["hello", "hi"]


def test_normalize_words_keeps_decimals_and_drops_thousands_separators():
    assert normalize_words("USG 1.052, then 2,000 milligrams.") == ["usg", "1.052", "then", "2000", "milligram"]


def test_normalize_words_treats_unit_abbreviations_and_plurals_alike():
    spelled = normalize_words("16 milligrams, 6.8 kilograms, 0.24 milliliters, 15 percent")
    abbreviated = normalize_words("16 mg, 6.8 kg, 0.24 mL, 15%")
    assert spelled == abbreviated == [
        "16", "milligram", "6.8", "kilogram", "0.24", "milliliter", "15", "percent"
    ]


def test_normalize_words_reads_symbols_the_way_they_are_spoken():
    assert normalize_words("grade 4/6, 3+ blood, $650, Dr. Chen") == normalize_words(
        "grade 4 out of 6, 3 plus blood, 650 dollars, Doctor Chen"
    )


def test_normalize_words_splits_hyphens_and_unifies_apostrophes():
    assert normalize_words("Epi-Otic, Hill’s c/d") == ["epi", "otic", "hill's", "c", "d"]


def test_word_error_rate_is_zero_for_identical_text():
    assert word_error_rate(["a", "b", "c"], ["a", "b", "c"]) == 0.0


def test_word_error_rate_counts_substitutions_insertions_and_deletions():
    # 1 substitution (b->x), 1 deletion (d), 1 insertion (y) over 4 reference words
    assert word_error_rate(["a", "b", "c", "d"], ["a", "x", "c", "y"]) == pytest.approx(2 / 4)
    assert word_error_rate(["a", "b", "c", "d"], ["a", "x", "c", "d", "y"]) == pytest.approx(2 / 4)


def test_word_error_rate_of_an_empty_transcript_is_one():
    assert word_error_rate(["a", "b"], []) == 1.0


def test_term_recall_matches_variants_after_normalizing():
    terms = [("16 milligram",), ("Vetmedin", "pimobendan"), ("4 out of 6",), ("Osurnia",)]
    transcript = "Apoquel 16 mg twice daily. Start Pimobendan. Murmur is 4/6."
    found, missing = term_recall(terms, transcript)
    # Reported by each term's first (canonical) spelling.
    assert found == ["16 milligram", "Vetmedin", "4 out of 6"]
    assert missing == ["Osurnia"]


def test_term_recall_needs_whole_words():
    found, missing = term_recall([("ALT",)], "We'll alter the plan.")
    assert found == [] and missing == ["ALT"]


def test_window_recall_reports_the_share_of_reference_words_heard_per_window():
    segments = [
        {"kind": "turn", "speaker": "Veterinarian", "start": 0.0, "end": 10.0, "text": "one two three four"},
        {"kind": "pause", "start": 10.0, "end": 300.0, "note": "exam"},
        {"kind": "turn", "speaker": "Owner", "start": 300.0, "end": 310.0, "text": "five six seven eight"},
    ]
    # The transcript stops partway: the second window only got half its words.
    windows = window_recall(segments, normalize_words("one two three four five six"), window_s=300)
    assert windows == [(0, 1.0), (300, 0.5)]


def test_window_recall_skips_windows_with_no_speech():
    segments = [
        {"kind": "turn", "speaker": "Veterinarian", "start": 0.0, "end": 5.0, "text": "hello"},
        {"kind": "pause", "start": 5.0, "end": 700.0, "note": "exam"},
        {"kind": "turn", "speaker": "Owner", "start": 700.0, "end": 705.0, "text": "bye"},
    ]
    assert window_recall(segments, ["hello", "bye"], window_s=300) == [(0, 1.0), (600, 1.0)]


def test_speaker_label_rate_counts_labelled_lines():
    transcript = "Veterinarian: hi\nOwner: hello\n\nand an unlabelled line\nSpeaker 3: ok"
    assert speaker_label_rate(transcript) == pytest.approx(3 / 4)

