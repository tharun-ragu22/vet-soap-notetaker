"""Evals for NoteGenerator.generate() against a range of example transcripts (see cases.py),
run for real against a live Ollama-compatible endpoint rather than mocked HTTP.

Unlike tests/, this makes real network calls and depends on an external model server being
up, so it isn't picked up by `pytest` (testpaths=["tests"]); it's instead run as its own
`backend-evals` CI job (see ../../.github/workflows/ci.yml), or manually:

    OLLAMA_BASE_URL=https://your-tunnel.example.dev OLLAMA_NOTE_MODEL=gemma4:e4b \
      uv run python -m evals.note_generator_evals

Falls back to http://localhost:11434 / gemma4:e4b (BackendConfig's own defaults) if the env
vars aren't set. The same model doubles as the LLMJudge evaluator, so the whole run needs
no paid API keys. Cases run one at a time (Ollama serializes generation per model anyway)
with a generous OLLAMA_EVAL_TIMEOUT_SECONDS (default 300s) to cover slow CPU-only inference.
A case counts as passing only if it didn't error and every assertion (HasAllSoapFields,
LLMJudge) is true; exits non-zero unless at least REQUIRED_PASS_RATE of cases pass,
tolerating some flakiness from a small local model rather than requiring a perfect run.
"""

import asyncio
import os
import sys

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_evals import Dataset
from pydantic_evals.evaluators import LLMJudge

from evals.cases import CASES
from evals.evaluators import FieldKeywordCoverage, HasAllSoapFields
from vetscribe_backend.llm.note_generation.ollama_note_generator import OllamaNoteGenerator
from vetscribe_backend.schemas import SoapNote

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_NOTE_MODEL = os.environ.get("OLLAMA_NOTE_MODEL", "gemma4:e4b")

# Ollama serializes generation per model by default (one request at a time), so a request
# queued behind another isn't actually slow, it's just waiting — this needs to be generous
# enough to cover CPU-only inference (e.g. CI runners with no GPU), not just genuine latency.
OLLAMA_EVAL_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_EVAL_TIMEOUT_SECONDS", "300"))

REQUIRED_PASS_RATE = 0.7

JUDGE_RUBRIC = (
    "The output is a SOAP note (subjective/objective/assessment/plan) generated from the "
    "veterinary exam-room transcript given as input. Judge whether it: "
    "(1) only includes clinically relevant facts actually present in the transcript, with no "
    "invented vitals, diagnoses, medications, or owner statements; "
    "(2) places each fact in the clinically correct SOAP section; "
    "(3) writes 'Not discussed' (or equivalent) for any section the transcript truly has no "
    "information for, rather than fabricating content to fill it; "
    "(4) ignores clinically irrelevant chit-chat (scheduling, weather, small talk) rather than "
    "including it in the note."
)


def build_dataset() -> Dataset[str, SoapNote, dict]:
    judge_model = OpenAIChatModel(
        OLLAMA_NOTE_MODEL,
        provider=OpenAIProvider(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama"),
    )
    return Dataset[str, SoapNote, dict](
        name="note_generator",
        cases=CASES,
        evaluators=[
            HasAllSoapFields(),
            FieldKeywordCoverage(),
            LLMJudge(rubric=JUDGE_RUBRIC, model=judge_model, include_input=True),
        ],
    )


async def generate_note(transcript: str) -> SoapNote:
    generator = OllamaNoteGenerator(
        base_url=OLLAMA_BASE_URL, model=OLLAMA_NOTE_MODEL, timeout_seconds=OLLAMA_EVAL_TIMEOUT_SECONDS
    )
    return await asyncio.to_thread(generator.generate, transcript)


def main() -> None:
    dataset = build_dataset()
    # max_concurrency=1: Ollama serializes generation per model server-side, so running
    # cases "concurrently" just queues them behind each other and burns each queued
    # request's client-side timeout while it waits, not while it's actually generating.
    report = dataset.evaluate_sync(generate_note, max_concurrency=1)
    report.print(include_input=False, include_output=True, include_durations=True)

    total_cases = len(report.cases) + len(report.failures)
    passed_cases = [
        case for case in report.cases if all(result.value for result in case.assertions.values())
    ]
    pass_rate = len(passed_cases) / total_cases if total_cases else 1.0

    for failure in report.failures:
        print(f"CASE ERRORED: {failure.name}: {failure.error_message}", file=sys.stderr)
    for case in report.cases:
        failed_assertions = [name for name, result in case.assertions.items() if not result.value]
        if failed_assertions:
            print(f"CASE FAILED: {case.name}: {', '.join(failed_assertions)}", file=sys.stderr)

    print(
        f"Pass rate: {len(passed_cases)}/{total_cases} ({pass_rate:.1%}), "
        f"required {REQUIRED_PASS_RATE:.0%}"
    )
    if pass_rate < REQUIRED_PASS_RATE:
        sys.exit(1)


if __name__ == "__main__":
    main()
