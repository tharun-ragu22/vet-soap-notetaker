from dataclasses import dataclass

from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from vetscribe_backend.schemas import SoapNote

SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")


@dataclass
class HasAllSoapFields(Evaluator[str, SoapNote, dict]):
    """Fails if generate() produced a blank string for any of the four SOAP fields."""

    def evaluate(self, ctx: EvaluatorContext[str, SoapNote, dict]) -> bool:
        note = ctx.output
        return all(getattr(note, field).strip() for field in SOAP_FIELDS)


@dataclass
class FieldKeywordCoverage(Evaluator[str, SoapNote, dict]):
    """Fraction of metadata['must_include'] keywords found (case-insensitively) in their
    matching SOAP field. Cases with no must_include entries trivially score 1.0."""

    def evaluate(self, ctx: EvaluatorContext[str, SoapNote, dict]) -> float:
        must_include: dict[str, list[str]] = (ctx.metadata or {}).get("must_include") or {}
        if not must_include:
            return 1.0

        note = ctx.output
        total = hits = 0
        for field, keywords in must_include.items():
            field_value = getattr(note, field).lower()
            for keyword in keywords:
                total += 1
                hits += keyword.lower() in field_value
        return hits / total
