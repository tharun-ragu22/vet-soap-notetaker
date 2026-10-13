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

    def capture_exception(self, exc, **kwargs):
        if self.fail:
            raise RuntimeError("network down")
        self.captured.append(("$exception", {"exc": exc, **kwargs}))


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
    # The SDK's own autocapture would send crashes with no user id; we install
    # our own hooks instead (install_crash_capture).
    assert not built.get("enable_exception_autocapture")
    assert built["before_send"] is analytics.scrub_exception_messages


# --- Crash capture -------------------------------------------------------------

import sys  # noqa: E402
import threading  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from vet_soap_notetaker.analytics import scrub_exception_messages  # noqa: E402


def _exception_event(value="backend returned 502: ZZ_PATIENT_SENTINEL"):
    return {
        "event": "$exception",
        "properties": {
            "$exception_list": [
                {
                    "type": "ApiClientError",
                    "value": value,
                    "stacktrace": {
                        "frames": [
                            {"function": "inject_note", "lineno": 7, "vars": {"note": value}}
                        ]
                    },
                }
            ],
            "$exception_message": value,
            "app": "desktop",
        },
    }


def test_scrubbing_keeps_the_type_and_stack_but_drops_messages_and_variables():
    event = scrub_exception_messages(_exception_event())

    entry = event["properties"]["$exception_list"][0]
    assert entry["type"] == "ApiClientError"
    assert entry["stacktrace"]["frames"][0]["function"] == "inject_note"
    assert "ZZ_PATIENT_SENTINEL" not in repr(event)


def test_scrubbing_leaves_ordinary_events_alone():
    event = {"event": "note_ready", "properties": {"wait_ms": 5}}
    assert scrub_exception_messages(event) == {"event": "note_ready", "properties": {"wait_ms": 5}}


def test_capture_exception_reports_as_the_user_with_shared_properties(monkeypatch):
    monkeypatch.setattr(analytics, "_app_version", lambda: "1.2.3")
    factory = Factory()
    tracker = DesktopAnalytics(make_config(), client_factory=factory)
    error = ValueError("boom")

    tracker.capture_exception(error)

    event, kwargs = factory.clients[0].captured[0]
    assert event == "$exception"
    assert kwargs["exc"] is error
    assert kwargs["distinct_id"] == "test-tharun"
    assert kwargs["properties"]["app"] == "desktop"


def test_capture_exception_is_a_no_op_when_off_and_never_raises():
    DesktopAnalytics(make_config(analytics_key=""), client_factory=Factory()).capture_exception(
        ValueError("x")
    )
    DesktopAnalytics(make_config(), client_factory=Factory(fail=True)).capture_exception(
        ValueError("x")
    )


def test_install_crash_capture_reports_uncaught_errors_then_runs_the_previous_hooks(monkeypatch):
    previous = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: previous.append("sys"))
    monkeypatch.setattr(threading, "excepthook", lambda args: previous.append("thread"))
    tk_root = MagicMock()
    original_tk_hook = tk_root.report_callback_exception
    tracker = DesktopAnalytics(make_config(), client_factory=Factory())
    captured = []
    monkeypatch.setattr(tracker, "capture_exception", captured.append)

    tracker.install_crash_capture(tk_root)
    main_error, thread_error, tk_error = ValueError("a"), KeyError("b"), TypeError("c")
    sys.excepthook(ValueError, main_error, None)
    threading.excepthook(
        MagicMock(exc_type=KeyError, exc_value=thread_error, exc_traceback=None)
    )
    tk_root.report_callback_exception(TypeError, tk_error, None)

    assert captured == [main_error, thread_error, tk_error]
    assert previous == ["sys", "thread"]
    original_tk_hook.assert_called_once_with(TypeError, tk_error, None)
