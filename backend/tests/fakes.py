class RecordingAnalytics:
    """In-memory stand-in for analytics.Analytics: records every event so tests
    can assert on what the backend would have sent to PostHog."""

    def __init__(self):
        self.events: list[dict] = []
        self.shut_down = False

    def capture(self, event: str, distinct_id: str, properties: dict) -> None:
        self.events.append(
            {"event": event, "distinct_id": distinct_id, "properties": dict(properties)}
        )

    def shutdown(self) -> None:
        self.shut_down = True

    def named(self, event: str) -> list[dict]:
        return [e for e in self.events if e["event"] == event]

    def only(self, event: str) -> dict:
        matches = self.named(event)
        assert len(matches) == 1, f"expected one {event!r}, got {self.events!r}"
        return matches[0]
