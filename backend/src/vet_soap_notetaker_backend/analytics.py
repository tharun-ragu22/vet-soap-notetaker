"""Product analytics (PostHog) for the backend.

Metadata only: event properties are ids, durations, counts, field names and
how much a box changed -- never audio, transcripts, note text or patient names.
Errors are reported by exception *type* (plus an upstream HTTP status), never
by message or traceback: an httpx error's text includes the provider URL, and
the Gemini providers put their API key in it.

An empty project key means analytics are off (:class:`NullAnalytics`), which is
the default for tests, CI and any clinic that opts out.
"""

import difflib
import logging
import re
from importlib import metadata
from typing import Protocol

import httpx
from posthog import Posthog

from vet_soap_notetaker_backend.config import BackendConfig

logger = logging.getLogger("vet_soap_notetaker_backend.analytics")


class Analytics(Protocol):
    def capture(self, event: str, distinct_id: str, properties: dict) -> None: ...

    def shutdown(self) -> None: ...


class NullAnalytics:
    """Analytics switched off: accepts every call and sends nothing."""

    def capture(self, event: str, distinct_id: str, properties: dict) -> None:
        pass

    def shutdown(self) -> None:
        pass


class PostHogAnalytics:
    """Sends events to PostHog, stamped with the properties every event shares.

    The client batches on its own background thread, so ``capture`` doesn't
    block the request. Analytics must never break a request either, so client
    failures are logged and swallowed."""

    def __init__(self, client, environment: str, app_version: str):
        self._client = client
        self._shared = {"app": "backend", "environment": environment, "app_version": app_version}

    def capture(self, event: str, distinct_id: str, properties: dict) -> None:
        try:
            self._client.capture(
                event, distinct_id=distinct_id, properties={**properties, **self._shared}
            )
        except Exception:
            logger.warning("Failed to record analytics event %s", event, exc_info=True)

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception:
            logger.warning("Failed to flush analytics on shutdown", exc_info=True)


def _app_version() -> str:
    try:
        return metadata.version("vet_soap_notetaker_backend")
    except metadata.PackageNotFoundError:  # e.g. a frozen build without metadata
        return "unknown"


def make_analytics(config: BackendConfig) -> Analytics:
    if not config.posthog_key:
        return NullAnalytics()
    # Exception autocapture stays off (the default): it would ship tracebacks
    # and messages, which can hold a provider URL with an API key in it.
    client = Posthog(config.posthog_key, host=config.posthog_host)
    return PostHogAnalytics(
        client, environment=config.analytics_environment, app_version=_app_version()
    )


# A provider error code ("INVALID_ARGUMENT", "API_KEY_INVALID", "invalid_api_key"):
# an identifier, so free text (which could quote the request) never matches.
_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _error_code(value) -> str | None:
    return value if isinstance(value, str) and _ERROR_CODE.fullmatch(value) else None


def _upstream_error_codes(response: httpx.Response) -> dict:
    """The codes in a provider's JSON error body -- Google's ``error.status`` and
    ``error.details[].reason``, or OpenAI/Anthropic's ``error.type`` and
    ``error.code`` -- never its ``message``."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return {}
    if not isinstance(error, dict):
        return {}
    status = _error_code(error.get("status")) or _error_code(error.get("type"))
    reason = _error_code(error.get("code"))
    details = error.get("details")
    if isinstance(details, list):
        reasons = (_error_code(d.get("reason")) for d in details if isinstance(d, dict))
        reason = next((r for r in reasons if r), None) or reason
    codes = {}
    if status:
        codes["upstream_error_status"] = status
    if reason:
        codes["upstream_error_reason"] = reason
    return codes


def error_properties(exc: Exception) -> dict:
    """Describe a failure without its message: the type, plus the upstream
    provider's HTTP status and error codes when there are some."""
    props: dict = {"error_type": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        props["upstream_status"] = exc.response.status_code
        props.update(_upstream_error_codes(exc.response))
    return props


def edit_summary(before: dict, after: dict, fields: tuple[str, ...]) -> dict:
    """How much the vet changed each box: the changed field names plus a 0-1
    similarity per field (1.0 = untouched). Carries no field text."""
    summary: dict = {}
    changed = []
    for field in fields:
        old, new = before.get(field, ""), after.get(field, "")
        similarity = 1.0 if old == new else round(difflib.SequenceMatcher(None, old, new).ratio(), 3)
        summary[f"{field}_similarity"] = similarity
        if old != new:
            changed.append(field)
    summary["fields_changed"] = changed
    summary["fields_changed_count"] = len(changed)
    return summary
