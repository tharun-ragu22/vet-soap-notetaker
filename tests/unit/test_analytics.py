import socket

import pytest

from vet_soap_notetaker import analytics
from vet_soap_notetaker.analytics import DesktopAnalytics
from vet_soap_notetaker.config import Config


class FakeClient:
    def __init__(self, key, host, fail=False):
        self.key = key
        self.host = host
        self.fail = fail
        self.captured = []
        self.shut_down = False

    def capture(self, event, **kwargs):
        if self.fail:
            raise RuntimeError("network down")
        self.captured.append((event, kwargs))

    def shutdown(self):
        if self.fail:
            raise RuntimeError("network down")
        self.shut_down = True


class Factory:
    def __init__(self, fail=False):
        self.clients = []
        self.fail = fail

    def __call__(self, key, host):
        client = FakeClient(key, host, fail=self.fail)
        self.clients.append(client)
        return client


def make_config(**overrides):
    defaults = dict(
        api_endpoint="https://example.test/api/soap",
        api_timeout_seconds=30,
        hotkey="<ctrl>+<shift>+r",
        analytics_key="phc_test",
        analytics_user_id="test-tharun",
        analytics_environment="test",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_without_a_key_nothing_is_built_or_sent():
    factory = Factory()
    tracker = DesktopAnalytics(make_config(analytics_key=""), client_factory=factory)

    tracker.capture("recording_started")
    tracker.shutdown()

    assert factory.clients == []
    assert tracker.enabled is False


def test_events_go_to_the_configured_user_with_the_shared_properties(monkeypatch):
    monkeypatch.setattr(analytics, "_app_version", lambda: "1.2.3")
    factory = Factory()
    tracker = DesktopAnalytics(make_config(), client_factory=factory)

    tracker.capture("recording_stopped", {"recording_ms": 5000})

    client = factory.clients[0]
    assert (client.key, client.host) == ("phc_test", "https://us.i.posthog.com")
    event, kwargs = client.captured[0]
    assert event == "recording_stopped"
    assert kwargs["distinct_id"] == "test-tharun"
    assert kwargs["properties"] == {
        "recording_ms": 5000,
        "app": "desktop",
        "environment": "test",
        "app_version": "1.2.3",
    }


def test_without_a_user_id_events_fall_back_to_this_machine():
    tracker = DesktopAnalytics(make_config(analytics_user_id=""), client_factory=Factory())
    assert tracker.distinct_id == f"desktop-{socket.gethostname()}"


def test_request_headers_identify_the_user_and_the_desktop_client():
    # Sent even with analytics off here: the backend may still have its own key.
    tracker = DesktopAnalytics(make_config(analytics_key=""), client_factory=Factory())
    assert tracker.request_headers() == {
        "X-POSTHOG-DISTINCT-ID": "test-tharun",
        "X-VSN-Client": "desktop",
    }


def test_reconfigure_switches_user_and_environment_live():
    factory = Factory()
    tracker = DesktopAnalytics(make_config(), client_factory=factory)

    tracker.reconfigure(make_config(analytics_user_id="demo-vet-1", analytics_environment="demo"))
    tracker.capture("app_started")

    assert len(factory.clients) == 1  # same key: the client is kept
    _, kwargs = factory.clients[0].captured[0]
    assert kwargs["distinct_id"] == "demo-vet-1"
    assert kwargs["properties"]["environment"] == "demo"
    assert tracker.request_headers()["X-POSTHOG-DISTINCT-ID"] == "demo-vet-1"


def test_reconfigure_with_a_new_key_flushes_the_old_client_and_builds_a_new_one():
    factory = Factory()
    tracker = DesktopAnalytics(make_config(), client_factory=factory)

    tracker.reconfigure(make_config(analytics_key="phc_other"))

    assert factory.clients[0].shut_down
    assert factory.clients[1].key == "phc_other"


def test_clearing_the_key_turns_analytics_off():
    factory = Factory()
    tracker = DesktopAnalytics(make_config(), client_factory=factory)

    tracker.reconfigure(make_config(analytics_key=""))
    tracker.capture("app_started")

    assert factory.clients[0].shut_down
    assert factory.clients[0].captured == []
    assert tracker.enabled is False


def test_client_failures_never_escape():
    tracker = DesktopAnalytics(make_config(), client_factory=Factory(fail=True))
    tracker.capture("app_started")
    tracker.shutdown()


def test_a_client_that_cannot_be_built_leaves_analytics_off():
    def broken_factory(key, host):
        raise ValueError("bad host")

    tracker = DesktopAnalytics(make_config(), client_factory=broken_factory)
    tracker.capture("app_started")
    assert tracker.enabled is False


def test_the_default_client_is_posthog_without_exception_or_variable_capture(monkeypatch):
    built = {}

    def fake_posthog(key, **kwargs):
        built["key"] = key
        built.update(kwargs)
        return FakeClient(key, kwargs.get("host"))

    monkeypatch.setattr(analytics, "Posthog", fake_posthog)

    DesktopAnalytics(make_config(analytics_host="https://eu.i.posthog.com"))

    assert built["key"] == "phc_test"
    assert built["host"] == "https://eu.i.posthog.com"
    assert not built.get("capture_exception_code_variables")
