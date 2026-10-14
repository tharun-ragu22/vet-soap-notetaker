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
import sys
import threading
from importlib import metadata

from posthog import Posthog

logger = logging.getLogger("vet_soap_notetaker.analytics")


def _app_version() -> str:
    try:
        return metadata.version("vet_soap_notetaker_assistant")
    except metadata.PackageNotFoundError:  # e.g. a frozen build without metadata
        return "unknown"


def scrub_exception_messages(event):
    """PostHog ``before_send`` hook: strip error *messages* from crash reports.

    Keeps each exception's type and stack (file, function, line -- our own
    code), drops its message and any captured variables: an ApiClientError's
    message carries a backend response body, and a frame's variables can hold
    the note or transcript. Ordinary events pass through unchanged.
    """
    if not event or event.get("event") != "$exception":
        return event
    properties = event.get("properties") or {}
    for entry in properties.get("$exception_list") or []:
        entry["value"] = ""
        for frame in (entry.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    for key in ("$exception_message", "$exception_values"):
        properties.pop(key, None)
    return event


def _posthog_client(key: str, host: str):
    # The SDK's own exception autocapture stays off (it sends crashes with no
    # user id) -- see install_crash_capture. Local-variable capture stays off
    # too, and every event passes through the message scrubber.
    return Posthog(
        key,
        host=host,
        capture_exception_code_variables=False,
        before_send=scrub_exception_messages,
    )


def injection_properties(
    source,
    result,
    injected,
    calibrated=False,
    fallback_flyout_shown=False,
    exam_id=None,
    request_id=None,
) -> dict:
    """Properties for an ``injection_completed`` event -- the same keys for every
    source (hotkey / flyout / history / remote), so dashboards never have to
    special-case one. ``result`` is ``AvimarkInjector.last_result``."""
    return {
        "source": source,
        "exam_id": exam_id,
        "request_id": request_id,
        "result": result,
        "calibrated": calibrated,
        "fallback_flyout_shown": fallback_flyout_shown,
        "injected": injected,
    }


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

    def capture_exception(self, exc: BaseException) -> None:
        # A crash report for PostHog's Error Tracking: type + stack only (the
        # message is scrubbed by scrub_exception_messages before sending).
        if self._client is None:
            return
        shared = {"app": "desktop", "environment": self.environment, "app_version": self._version}
        try:
            self._client.capture_exception(
                exc, distinct_id=self.distinct_id, properties=shared
            )
        except Exception:
            logger.warning("Failed to record a crash report", exc_info=True)

    def install_crash_capture(self, tk_root) -> None:
        """Report every uncaught error -- main thread, background threads (the
        hotkey worker, offline queue, injection poller) and Tk callbacks (button
        handlers, after() jobs, which never reach sys.excepthook) -- then hand it
        on to whatever handled it before, so logging/printing is unchanged.
        Called once, from run(); the hooks read the live client, so a key
        entered later in Settings is picked up."""
        previous_sys_hook = sys.excepthook
        previous_thread_hook = threading.excepthook
        previous_tk_hook = tk_root.report_callback_exception

        def sys_hook(exc_type, exc_value, exc_traceback):
            self.capture_exception(exc_value)
            previous_sys_hook(exc_type, exc_value, exc_traceback)

        def thread_hook(args):
            self.capture_exception(args.exc_value)
            previous_thread_hook(args)

        def tk_hook(exc_type, exc_value, exc_traceback):
            self.capture_exception(exc_value)
            previous_tk_hook(exc_type, exc_value, exc_traceback)

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook
        tk_root.report_callback_exception = tk_hook

    def shutdown(self) -> None:
        # Flush whatever is batched. Called on quit and before swapping clients.
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            logger.warning("Failed to flush analytics", exc_info=True)
