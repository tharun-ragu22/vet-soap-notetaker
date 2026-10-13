"""Product analytics (PostHog) for the desktop app.

Metadata only: event properties are ids, durations, counts, outcomes and
field *names* -- never audio, transcripts, note text, patient names, or the
text of an error (``ApiClientError`` messages carry backend response bodies).

An empty ``analytics_key`` means analytics are off: nothing is built or sent.
That's the default, so tests, CI and clinics that opt out send nothing. The
key, user id and environment are set in Settings and applied live through
``reconfigure``.
"""

import logging
import socket
from importlib import metadata

from posthog import Posthog

logger = logging.getLogger("vet_soap_notetaker.analytics")


def _app_version() -> str:
    try:
        return metadata.version("vet_soap_notetaker_assistant")
    except metadata.PackageNotFoundError:  # e.g. a frozen build without metadata
        return "unknown"


def _posthog_client(key: str, host: str):
    # Local-variable capture stays off: a crashing frame's locals can hold the
    # note or transcript.
    return Posthog(key, host=host, capture_exception_code_variables=False)


class NullAnalytics:
    """Analytics switched off -- the default for components built without one."""

    def capture(self, event: str, properties: dict | None = None) -> None:
        pass


class DesktopAnalytics:
    """Sends events to PostHog as the configured user, stamped with the
    properties every event shares. The client batches on its own background
    thread, so ``capture`` is safe from any thread and never blocks. Analytics
    must never break the app either: every client failure is logged and
    swallowed."""

    def __init__(self, config, client_factory=None):
        self._client_factory = client_factory or _posthog_client
        self._client = None
        self._key = ""
        self._host = ""
        self.distinct_id = ""
        self.environment = ""
        self._version = _app_version()
        self.reconfigure(config)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def reconfigure(self, config) -> None:
        # Who and where can change freely; only a new key/host needs a new client.
        self.distinct_id = config.analytics_user_id or f"desktop-{socket.gethostname()}"
        self.environment = config.analytics_environment
        if (config.analytics_key, config.analytics_host) == (self._key, self._host):
            return
        self.shutdown()
        self._client = None
        self._key, self._host = config.analytics_key, config.analytics_host
        if not self._key:
            return
        try:
            self._client = self._client_factory(self._key, self._host)
        except Exception:
            logger.warning("Could not start analytics; continuing without them", exc_info=True)

    def request_headers(self) -> dict:
        # Sent to the backend on every request (even with analytics off here --
        # the backend may have its own key), so its events land on this user.
        return {"X-POSTHOG-DISTINCT-ID": self.distinct_id, "X-VSN-Client": "desktop"}

    def capture(self, event: str, properties: dict | None = None) -> None:
        if self._client is None:
            return
        shared = {"app": "desktop", "environment": self.environment, "app_version": self._version}
        try:
            self._client.capture(
                event, distinct_id=self.distinct_id, properties={**(properties or {}), **shared}
            )
        except Exception:
            logger.warning("Failed to record analytics event %s", event, exc_info=True)

    def shutdown(self) -> None:
        # Flush whatever is batched. Called on quit and before swapping clients.
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            logger.warning("Failed to flush analytics", exc_info=True)
