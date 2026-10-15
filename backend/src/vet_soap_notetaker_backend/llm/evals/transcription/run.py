"""Latency + accuracy evals for Transcriber.transcribe(), run for real against the configured
provider rather than mocked HTTP.

Each synthetic exam recording (5/10/20/30 min, see cases.py) goes through the
exact production transcriber -- get_transcriber(BackendConfig.from_env()), so the same model,
retries, timeouts and inline-vs-Files-API switch the clinic backend uses -- in both formats the
backend receives (phone .m4a, desktop .wav). Evaluators (evaluators.py) check
latency, word error rate, clinical-term recall, and recall per 5-minute window (does a long
recording degrade or stop partway?).

The audio isn't in git (~300 MB): generate it with backend/scripts/transcription_eval_audio.ipynb
and unzip it into llm/evals/transcription/eval_audio/ (or point VETSCRIBE_EVAL_AUDIO_DIR at it). Like
note_generation/run.py this isn't picked up by `pytest`; run it from backend/ with the provider
key in backend/.env or the environment:

    uv run python -m vet_soap_notetaker_backend.llm.evals.transcription.run
    uv run python -m vet_soap_notetaker_backend.llm.evals.transcription.run --formats phone --only otitis_hotspot_5min

Costs real money (roughly $0.25 for a full run on gemini-2.5-flash). Cases run one at a time
(max_concurrency=1) so each latency is the provider's alone, not time spent queued behind
another upload. Transcripts and results.json land in llm/evals/transcription/results/
<timestamp>/ (gitignored). Exits non-zero unless REQUIRED_PASS_RATE of cases pass every
assertion.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from pydantic_evals import Case, Dataset

from vet_soap_notetaker_backend.config import BackendConfig
from vet_soap_notetaker_backend.llm.evals.transcription.cases import KEY_TERMS
from vet_soap_notetaker_backend.llm.evals.transcription.evaluators import (
    ClinicalTermRecall,
    NoLateDropoff,
    SpeakerLabelRate,
    TranscriptionInput,
    WithinLatencyBudget,
    WordErrorRate,
)
from vet_soap_notetaker_backend.llm.evals.transcription.scoring import term_recall
from vet_soap_notetaker_backend.llm.transcription import Transcriber, get_transcriber

EVALS_DIR = Path(__file__).parent
DEFAULT_AUDIO_DIR = Path(os.environ.get("VETSCRIBE_EVAL_AUDIO_DIR", EVALS_DIR / "eval_audio"))
RESULTS_DIR = EVALS_DIR / "results"
FORMATS = ("phone", "desktop")

# Every recording is a realistic exam the vet could send, so all of them must pass --
# unlike the note evals there's no small local model whose flakiness needs tolerating.
REQUIRED_PASS_RATE = 1.0


def _upload_path(transcriber: Transcriber, num_bytes: int) -> str:
    # Mirrors GeminiTranscriber.transcribe(): base64 size over the inline ceiling -> Files API.
    limit = getattr(transcriber, "inline_max_bytes", None)
    if limit is None:
        return "n/a"
    return "files_api" if (num_bytes + 2) // 3 * 4 > limit else "inline"


def build_cases(audio_dir: Path, formats, only, transcriber) -> list[Case[TranscriptionInput, str, dict]]:
    manifest_path = audio_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(
            f"No {manifest_path}. Generate the audio with backend/scripts/transcription_eval_audio.ipynb "
            "and unzip it there (or set VETSCRIBE_EVAL_AUDIO_DIR)."
        )
    recordings = json.loads(manifest_path.read_text())["recordings"]
    unknown = set(only or ()) - {r["name"] for r in recordings}
    if unknown:
        raise SystemExit(f"unknown recording(s): {', '.join(sorted(unknown))}")

    cases = []
    for recording in recordings:
        name = recording["name"]
        if only and name not in only:
            continue
        reference = (audio_dir / recording["files"]["reference"]).read_text()
        terms = KEY_TERMS.get(name, [])
        # A term the reference itself lacks is a typo in KEY_TERMS, not a transcription
        # miss -- refuse to run rather than report a fake failure.
        _, absent = term_recall(terms, reference)
        if absent:
            raise SystemExit(f"{name}: KEY_TERMS not in the reference transcript: {absent}")
        segments = json.loads((audio_dir / recording["files"]["segments"]).read_text())
        for fmt in formats:
            path = audio_dir / recording["files"][fmt]
            size = path.stat().st_size
            cases.append(Case(
                name=f"{name} [{fmt}]",
                inputs=TranscriptionInput(name=name, format=fmt, audio_path=str(path)),
                expected_output=reference,
                metadata={
                    "audio_min": round(recording["duration_ms"] / 60000, 1),
                    "audio_mb": round(size / 1e6, 1),
                    "upload_path": _upload_path(transcriber, size),
                    "terms": terms,
                    "segments": segments,
                },
            ))
    return cases


def build_dataset(cases) -> Dataset[TranscriptionInput, str, dict]:
    return Dataset[TranscriptionInput, str, dict](
        name="transcription",
        cases=cases,
        evaluators=[
            WithinLatencyBudget(),
            WordErrorRate(),
            ClinicalTermRecall(),
            NoLateDropoff(),
            SpeakerLabelRate(),
        ],
    )


def save_results(report, provider: str, model: str) -> Path:
    out_dir = RESULTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True)
    results = []
    for case in report.cases:
        (out_dir / f"{case.inputs.name}.{case.inputs.format}.txt").write_text(case.output)
        results.append({
            "case": case.name,
            "audio_min": case.metadata["audio_min"],
            "audio_mb": case.metadata["audio_mb"],
            "upload_path": case.metadata["upload_path"],
            "seconds": round(case.task_duration, 1),
            "scores": {k: round(v.value, 4) for k, v in case.scores.items()},
            "assertions": {k: {"pass": v.value, "reason": v.reason} for k, v in case.assertions.items()},
        })
    for failure in report.failures:
        results.append({"case": failure.name, "error": failure.error_message})
    (out_dir / "results.json").write_text(
        json.dumps({"provider": provider, "model": model, "results": results}, indent=2)
    )
    return out_dir


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--formats", nargs="+", choices=FORMATS, default=list(FORMATS))
    parser.add_argument("--only", nargs="+", help="recording names from manifest.json (default: all)")
    args = parser.parse_args(argv)

    # The transcriber logs retries and the switch to the Files API -- worth seeing live.
    logging.basicConfig(level=logging.INFO, format="    %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = BackendConfig.from_env()
    transcriber = get_transcriber(config)
    model = getattr(transcriber, "model", "?")
    cases = build_cases(args.audio_dir, args.formats, args.only, transcriber)
    print(f"Transcriber: {config.transcription_provider} ({model}), {len(cases)} cases")
    for case in cases:
        meta = case.metadata
        print(f"  {case.name:<46} {meta['audio_min']:>5.1f} min {meta['audio_mb']:>6.1f} MB  {meta['upload_path']}")

    async def transcribe(inputs: TranscriptionInput) -> str:
        audio = Path(inputs.audio_path).read_bytes()
        return await asyncio.to_thread(transcriber.transcribe, audio)

    # max_concurrency=1: concurrent uploads would share bandwidth and provider capacity,
    # so each case's duration would no longer be its own latency.
    report = build_dataset(cases).evaluate_sync(transcribe, max_concurrency=1)
    report.print(include_input=False, include_output=False, include_durations=True)

    total_cases = len(report.cases) + len(report.failures)
    passed_cases = [
        case for case in report.cases if all(result.value for result in case.assertions.values())
    ]
    pass_rate = len(passed_cases) / total_cases if total_cases else 1.0

    for failure in report.failures:
        print(f"CASE ERRORED: {failure.name}: {failure.error_message}", file=sys.stderr)
    for case in report.cases:
        failed = [f"{name} ({result.reason})" for name, result in case.assertions.items() if not result.value]
        if failed:
            print(f"CASE FAILED: {case.name}: {'; '.join(failed)}", file=sys.stderr)

    out_dir = save_results(report, config.transcription_provider, model)
    print(f"Transcripts and results.json: {out_dir}")
    print(
        f"Pass rate: {len(passed_cases)}/{total_cases} ({pass_rate:.1%}), "
        f"required {REQUIRED_PASS_RATE:.0%}"
    )
    if pass_rate < REQUIRED_PASS_RATE:
        sys.exit(1)


if __name__ == "__main__":
    main()
