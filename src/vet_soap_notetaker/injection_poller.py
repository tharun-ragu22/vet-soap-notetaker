import logging
import threading

from vet_soap_notetaker.api_client import ApiClientError

logger = logging.getLogger("vet_soap_notetaker.injection_poller")


class InjectionPoller:
    """Polls the backend for mobile-originated "inject this note into AVImark"
    requests and hands each one to a callback.

    This is the desktop half of the remote-injection bridge. It mirrors
    ``OfflineQueue``: a daemon thread polls on an interval (default 3s, far
    tighter than the offline queue's 60s because the vet is waiting at the PC),
    and network failures are swallowed so a flaky backend just means the next
    poll retries.

    Threading: this runs on a background thread, but ``on_injection`` almost
    certainly needs to touch Tk (show a flyout) or Win32 (paste), so the wiring
    in ``main.py`` marshals it onto the main thread via ``run_on_main_thread``.
    Because that dispatch is asynchronous, we can't learn the real paste outcome
    here, so we ack with ``"delivered"`` — the ack only means "the desktop
    received this request", which is what stops it being re-delivered.

    Each request is dispatched exactly once: once we've handed a request id to
    ``on_injection`` we record it in ``_handled`` and never dispatch it again,
    even if the ack call fails and the backend keeps returning it — re-pasting
    the same note into a chart is worse than dropping a lost ack. A request that
    fails to dispatch (the callback raised) is *not* recorded, so it retries."""

    def __init__(self, api_client, on_injection, poll_interval_seconds=3):
        self.api_client = api_client
        self.on_injection = on_injection
        self.poll_interval_seconds = poll_interval_seconds
        self._handled: set[str] = set()
        self._stop_event = threading.Event()
        self._thread = None

    def process_once(self):
        try:
            requests = self.api_client.fetch_pending_injections()
        except ApiClientError as exc:
            logger.info("injection poll failed, will retry: %s", exc)
            return []

        handled = []
        for req in requests:
            req_id = req.get("id")
            if req_id in self._handled:
                continue
            try:
                self.on_injection(req)
            except Exception:
                # Dispatch failed: don't ack, don't mark handled -- retry next
                # poll. One bad request must not block the rest.
                logger.exception("failed to dispatch injection %s", req_id)
                continue
            self._handled.add(req_id)
            try:
                self.api_client.ack_injection(req_id, outcome="delivered")
            except ApiClientError as exc:
                # Already dispatched; a lost ack must not cause a re-paste.
                logger.warning(
                    "failed to ack injection %s (already dispatched, won't retry): %s",
                    req_id,
                    exc,
                )
            handled.append(req_id)
        return handled

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(self.poll_interval_seconds):
            self.process_once()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
