import httpx
import pytest

from vet_soap_notetaker_backend import analytics
from vet_soap_notetaker_backend.analytics import (
    NullAnalytics,
    PostHogAnalytics,
    edit_summary,
    error_properties,
    make_analytics,
)
from vet_soap_notetaker_backend.llm.note_generation.parsing import NoteParsingError


class FakeClient:
    def __init__(self, fail=False):
        self.captured = []
        self.fail = fail
        self.shut_down = False

    def capture(self, event, **kwargs):
        if self.fail:
            raise RuntimeError("network down")
        self.captured.append((event, kwargs))

    def shutdown(self):
        if self.fail:
            raise RuntimeError("network down")
        self.shut_down = True


def test_make_analytics_is_a_no_op_without_a_project_key(make_config):
    assert isinstance(make_analytics(make_config(posthog_key="")), NullAnalytics)


def test_make_analytics_builds_a_posthog_client_for_the_configured_host(make_config, monkeypatch):
    built = {}

    class FakePosthog(FakeClient):
        def __init__(self, project_api_key, **kwargs):
            super().__init__()
            built["key"] = project_api_key
            built.update(kwargs)

    monkeypatch.setattr(analytics, "Posthog", FakePosthog)

    result = make_analytics(
        make_config(posthog_key="phc_test", posthog_host="https://us.i.posthog.com")
    )

    assert isinstance(result, PostHogAnalytics)
    assert built["key"] == "phc_test"
    assert built["host"] == "https://us.i.posthog.com"
    # Exception autocapture would ship tracebacks + messages, which can hold a
    # provider URL with the Gemini API key in it, or model output.
    assert not built.get("enable_exception_autocapture")


def test_null_analytics_accepts_events_and_shutdown():
    null = NullAnalytics()
    null.capture("anything", "someone", {"a": 1})
    null.shutdown()


def test_posthog_analytics_adds_the_shared_properties_to_every_event():
    client = FakeClient()
    tracker = PostHogAnalytics(client=client, environment="demo", app_version="1.2.3")

    tracker.capture("note_saved", "demo-vet-1", {"exam_id": "e1"})

    event, kwargs = client.captured[0]
    assert event == "note_saved"
    assert kwargs["distinct_id"] == "demo-vet-1"
    assert kwargs["properties"] == {
        "exam_id": "e1",
        "app": "backend",
        "environment": "demo",
        "app_version": "1.2.3",
    }


def test_posthog_analytics_never_raises_when_the_client_fails():
    tracker = PostHogAnalytics(client=FakeClient(fail=True), environment="demo", app_version="1")

    tracker.capture("note_saved", "demo-vet-1", {})
    tracker.shutdown()


def test_posthog_analytics_shutdown_flushes_the_client():
    client = FakeClient()
    PostHogAnalytics(client=client, environment="demo", app_version="1").shutdown()
    assert client.shut_down


FIELDS = ("subjective", "objective", "assessment", "plan", "transcript")


def _fields(**overrides):
    base = {f: f"original {f} text" for f in FIELDS}
    base.update(overrides)
    return base


def test_edit_summary_reports_no_changes_for_identical_fields():
    summary = edit_summary(_fields(), _fields(), FIELDS)

    assert summary["fields_changed"] == []
    assert summary["fields_changed_count"] == 0
    for field in FIELDS:
        assert summary[f"{field}_similarity"] == 1.0


def test_edit_summary_reports_which_fields_changed_and_by_how_much():
    before = _fields()
    after = _fields(plan="a completely rewritten plan", objective="original objective text!")

    summary = edit_summary(before, after, FIELDS)

    assert summary["fields_changed"] == ["objective", "plan"]
    assert summary["fields_changed_count"] == 2
    assert 0.9 < summary["objective_similarity"] < 1.0
    assert summary["plan_similarity"] < 0.6
    assert summary["subjective_similarity"] == 1.0


def test_edit_summary_carries_no_field_text():
    after = _fields(plan="ZZ_PATIENT_SENTINEL")
    summary = edit_summary(_fields(), after, FIELDS)
    assert "ZZ_PATIENT_SENTINEL" not in repr(summary)


def test_error_properties_give_the_type_and_upstream_status_but_not_the_message():
    request = httpx.Request("POST", "https://provider.example/v1?key=SECRET_KEY")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("503 for url ...?key=SECRET_KEY", request=request, response=response)

    props = error_properties(exc)

    assert props == {"error_type": "HTTPStatusError", "upstream_status": 503}


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("boom ?key=SECRET_KEY"),
        NoteParsingError("model did not return valid JSON: ZZ_PATIENT_SENTINEL"),
    ],
)
def test_error_properties_for_other_errors_are_just_the_type(exc):
    props = error_properties(exc)
    assert props == {"error_type": type(exc).__name__}


def _status_error(status, body, url="https://provider.example/v1/models/m:gen?key=SECRET_KEY"):
    request = httpx.Request("POST", url)
    response = httpx.Response(status, request=request, content=body)
    return httpx.HTTPStatusError(f"{status} for url {url}", request=request, response=response)


GEMINI_BAD_KEY = (
    b'{"error": {"code": 400, "message": "API key not valid. ZZ_PATIENT_SENTINEL", '
    b'"status": "INVALID_ARGUMENT", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", '
    b'"reason": "API_KEY_INVALID", "domain": "googleapis.com"}]}}'
)


def test_error_properties_name_the_providers_error_codes_but_not_its_message():
    props = error_properties(_status_error(400, GEMINI_BAD_KEY))

    assert props == {
        "error_type": "HTTPStatusError",
        "upstream_status": 400,
        "upstream_error_status": "INVALID_ARGUMENT",
        "upstream_error_reason": "API_KEY_INVALID",
    }


def test_error_properties_read_openai_style_error_codes():
    body = b'{"error": {"message": "Incorrect API key ZZ", "type": "invalid_request_error", "code": "invalid_api_key"}}'

    props = error_properties(_status_error(401, body))

    assert props["upstream_error_status"] == "invalid_request_error"
    assert props["upstream_error_reason"] == "invalid_api_key"


@pytest.mark.parametrize("body", [b"", b"<html>Bad Gateway</html>", b'["not", "an", "object"]',
                                  b'{"error": "plain text error ZZ_PATIENT_SENTINEL"}'])
def test_error_properties_fall_back_to_the_status_for_an_unrecognised_body(body):
    props = error_properties(_status_error(502, body))

    assert props == {"error_type": "HTTPStatusError", "upstream_status": 502}


def test_error_properties_drop_codes_that_are_not_code_shaped():
    # Only short identifier-like codes are sent: free text could carry anything.
    body = b'{"error": {"status": "the audio said ZZ_PATIENT_SENTINEL", "details": [{"reason": "a b c"}]}}'

    props = error_properties(_status_error(400, body))

    assert props == {"error_type": "HTTPStatusError", "upstream_status": 400}
