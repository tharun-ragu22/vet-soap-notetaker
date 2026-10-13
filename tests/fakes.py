class RecordingAnalytics:
    """In-memory stand-in for analytics.DesktopAnalytics: records every event so
    tests can assert on what the desktop app would have sent to PostHog."""

    def __init__(self, distinct_id="test-user"):
        self.distinct_id = distinct_id
        self.events: list[dict] = []
        self.reconfigured = []
        self.shut_down = False

    def capture(self, event, properties=None):
        self.events.append({"event": event, "properties": dict(properties or {})})

    def request_headers(self):
        return {"X-POSTHOG-DISTINCT-ID": self.distinct_id, "X-VSN-Client": "desktop"}

    def reconfigure(self, config):
        self.reconfigured.append(config)

    def shutdown(self):
        self.shut_down = True

    def named(self, event):
        return [e for e in self.events if e["event"] == event]

    def only(self, event):
        matches = self.named(event)
        assert len(matches) == 1, f"expected one {event!r}, got {self.events!r}"
        return matches[0]
