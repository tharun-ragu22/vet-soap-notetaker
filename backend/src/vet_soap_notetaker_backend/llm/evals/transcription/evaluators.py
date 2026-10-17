"""pydantic-evals evaluators for Transcriber.transcribe() (see run.py).

Each case's output is the transcript, expected_output the exact text that was spoken,
and metadata carries the per-turn timings ("segments") and the clinical "terms" that
must come through. Assertions are the pass bars; the numbers behind them are scores.
"""

from dataclasses import dataclass

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from vet_soap_notetaker_backend.llm.evals.transcription.scoring import (
    normalize_words,
    speaker_label_rate,
    term_recall,
    window_recall,
    word_error_rate,
)

# The phone gives up after 480s and note generation still has to run after
# transcription, so transcription alone must leave real headroom.
MAX_LATENCY_SECONDS = 300.0
MAX_WER = 0.15
MIN_TERM_RECALL = 0.90
MIN_WINDOW_RECALL = 0.80
WINDOW_SECONDS = 300
# Words a short clip's transcript may hold per word actually said; more is invented speech.
MAX_SHORT_CLIP_WORD_RATIO = 1.5


@dataclass(frozen=True)
class TranscriptionInput:
    name: str          # recording name from manifest.json
    format: str        # "phone" (.m4a) or "desktop" (.wav)
    audio_path: str


@dataclass
class WithinLatencyBudget(Evaluator[TranscriptionInput, str, dict]):
    """Fails if transcribe() took longer than max_seconds (pydantic-evals' own task timing)."""

    max_seconds: float = MAX_LATENCY_SECONDS

    def evaluate(self, ctx: EvaluatorContext[TranscriptionInput, str, dict]) -> EvaluationReason:
        return EvaluationReason(
            value=ctx.duration <= self.max_seconds,
            reason=f"{ctx.duration:.0f}s (budget {self.max_seconds:.0f}s)",
        )


@dataclass
class WordErrorRate(Evaluator[TranscriptionInput, str, dict]):
    """Word error rate against the spoken text, after normalize_words()."""

    max_wer: float = MAX_WER

    def evaluate(self, ctx: EvaluatorContext[TranscriptionInput, str, dict]) -> dict:
        wer = word_error_rate(normalize_words(ctx.expected_output or ""), normalize_words(ctx.output))
        return {
            "wer": wer,
            "wer_ok": EvaluationReason(value=wer <= self.max_wer, reason=f"{wer:.1%} (max {self.max_wer:.0%})"),
        }


@dataclass
class ClinicalTermRecall(Evaluator[TranscriptionInput, str, dict]):
    """Fraction of metadata['terms'] (vitals, doses, drug names) found in the transcript."""

    min_recall: float = MIN_TERM_RECALL

    def evaluate(self, ctx: EvaluatorContext[TranscriptionInput, str, dict]) -> dict:
        terms = (ctx.metadata or {}).get("terms") or []
        found, missing = term_recall(terms, ctx.output)
        recall = len(found) / len(terms) if terms else 1.0
        reason = f"missed: {', '.join(missing)}" if missing else "all terms found"
        return {
            "term_recall": recall,
            "terms_ok": EvaluationReason(value=recall >= self.min_recall, reason=reason),
        }


@dataclass
class NoLateDropoff(Evaluator[TranscriptionInput, str, dict]):
    """Worst per-window recall of the spoken words -- catches a long recording whose
    transcript degrades or stops partway through."""

    min_window_recall: float = MIN_WINDOW_RECALL
    window_seconds: float = WINDOW_SECONDS

    def evaluate(self, ctx: EvaluatorContext[TranscriptionInput, str, dict]) -> dict:
        segments = (ctx.metadata or {}).get("segments") or []
        windows = window_recall(segments, normalize_words(ctx.output), self.window_seconds)
        start, worst = min(windows, key=lambda w: w[1]) if windows else (0, 1.0)
        minute = int(start // 60)
        return {
            "worst_window_recall": worst,
            "windows_ok": EvaluationReason(
                value=worst >= self.min_window_recall,
                reason=f"worst: minute {minute}-{minute + int(self.window_seconds // 60)} heard {worst:.0%}",
            ),
        }


@dataclass
class SpeakerLabelRate(Evaluator[TranscriptionInput, str, dict]):
    """Share of transcript lines that start with a speaker label (informational)."""

    def evaluate(self, ctx: EvaluatorContext[TranscriptionInput, str, dict]) -> float:
        return speaker_label_rate(ctx.output)


@dataclass
class NoInventedSpeech(Evaluator[TranscriptionInput, str, dict]):
    """For the short and silent clips: the transcript must not hold words nobody
    said. A silent clip must come back empty (the transcriber's NoSpeechError);
    a spoken one may be at most max_ratio times as long as what was said."""

    max_ratio: float = MAX_SHORT_CLIP_WORD_RATIO

    def evaluate(self, ctx: EvaluatorContext[TranscriptionInput, str, dict]) -> dict:
        said = len(normalize_words(ctx.expected_output or ""))
        heard = len(normalize_words(ctx.output))
        if said == 0:
            ok, reason = heard == 0, f"{heard} words from a silent clip"
        else:
            ok = heard <= said * self.max_ratio
            reason = f"{heard} words for {said} spoken (max {self.max_ratio:g}x)"
        return {"no_invented_speech": EvaluationReason(value=ok, reason=reason)}
