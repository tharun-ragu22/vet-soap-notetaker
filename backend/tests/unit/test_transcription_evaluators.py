from pydantic_evals.evaluators import EvaluatorContext

from vet_soap_notetaker_backend.llm.evals.transcription.evaluators import (
    ClinicalTermRecall,
    NoLateDropoff,
    SpeakerLabelRate,
    TranscriptionInput,
    WithinLatencyBudget,
    WordErrorRate,
)

REFERENCE = "Veterinarian: Give Vetmedin 2.5 milligrams twice a day.\nOwner: Okay, twice a day.\n"
SEGMENTS = [
    {"kind": "turn", "speaker": "Veterinarian", "start": 0.0, "end": 4.0,
     "text": "Give Vetmedin 2.5 milligrams twice a day."},
    {"kind": "pause", "start": 4.0, "end": 400.0, "note": "exam"},
    {"kind": "turn", "speaker": "Owner", "start": 400.0, "end": 402.0, "text": "Okay, twice a day."},
]
METADATA = {"segments": SEGMENTS, "terms": [("Vetmedin", "pimobendan"), ("2.5 milligram",)]}


def _ctx(output, duration=10.0):
    return EvaluatorContext(
        name="case",
        inputs=TranscriptionInput(name="case", format="phone", audio_path="case.phone.m4a"),
        metadata=METADATA,
        expected_output=REFERENCE,
        output=output,
        duration=duration,
        _span_tree=None,
        attributes={},
        metrics={},
    )


GOOD = "Veterinarian: Give Vetmedin 2.5 mg twice a day.\nOwner: OK, twice a day."
CUT_OFF = "Veterinarian: Give Vetoryl 2.5 mg twice a day."  # wrong drug, and stops early


def test_within_latency_budget_uses_the_task_duration():
    assert WithinLatencyBudget(max_seconds=300).evaluate(_ctx(GOOD, duration=120)).value is True
    slow = WithinLatencyBudget(max_seconds=300).evaluate(_ctx(GOOD, duration=301))
    assert slow.value is False and "301" in slow.reason


def test_word_error_rate_scores_and_asserts():
    good = WordErrorRate(max_wer=0.15).evaluate(_ctx(GOOD))
    assert good["wer"] == 0.0 and good["wer_ok"].value is True
    bad = WordErrorRate(max_wer=0.15).evaluate(_ctx(CUT_OFF))
    assert bad["wer"] > 0.15 and bad["wer_ok"].value is False


def test_clinical_term_recall_names_the_missed_terms():
    good = ClinicalTermRecall(min_recall=0.9).evaluate(_ctx(GOOD))
    assert good["term_recall"] == 1.0 and good["terms_ok"].value is True
    bad = ClinicalTermRecall(min_recall=0.9).evaluate(_ctx(CUT_OFF))
    assert bad["term_recall"] == 0.5
    assert bad["terms_ok"].value is False and "Vetmedin" in bad["terms_ok"].reason


def test_no_late_dropoff_flags_the_window_that_went_quiet():
    good = NoLateDropoff(min_window_recall=0.8, window_seconds=300).evaluate(_ctx(GOOD))
    assert good["worst_window_recall"] == 1.0 and good["windows_ok"].value is True
    bad = NoLateDropoff(min_window_recall=0.8, window_seconds=300).evaluate(_ctx(CUT_OFF))
    assert bad["worst_window_recall"] == 0.0
    assert bad["windows_ok"].value is False and "minute 5" in bad["windows_ok"].reason


def test_speaker_label_rate_is_a_score():
    assert SpeakerLabelRate().evaluate(_ctx(GOOD)) == 1.0
    assert SpeakerLabelRate().evaluate(_ctx("give vetmedin")) == 0.0
