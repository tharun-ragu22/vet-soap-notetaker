import logging
from pathlib import Path

import pytest

from vet_soap_notetaker.log_forwarding import PostHogLogHandler

PREFIX = "vet_soap_notetaker"


class Capture:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def __call__(self, event, properties=None):
        if self.fail:
            raise RuntimeError("network down")
        self.events.append((event, properties))


@pytest.fixture
def forwarded():
    capture = Capture()
    handler = PostHogLogHandler(capture, prefix=PREFIX, loggers=("avimark_injector", "pipeline"))
    root = logging.getLogger(PREFIX)
    old_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    yield capture
    root.removeHandler(handler)
    root.setLevel(old_level)


def test_a_listed_logger_line_becomes_a_diagnostic_log_event(forwarded):
    logging.getLogger(f"{PREFIX}.avimark_injector").info("pasted %d chars into %r", 12, "plan")

    assert forwarded.events == [
        (
            "diagnostic_log",
            {
                "logger": "avimark_injector",
                "level": "INFO",
                "message": "pasted 12 chars into 'plan'",
            },
        )
    ]


def test_unlisted_loggers_and_debug_lines_are_not_forwarded(forwarded):
    logging.getLogger(f"{PREFIX}.history_ui").warning("not listed")
    logging.getLogger("somebody_else").warning("not ours")
    logging.getLogger(f"{PREFIX}.pipeline").debug("too chatty")

    assert forwarded.events == []


def test_an_exception_argument_is_sent_as_its_type_only(forwarded):
    error = ValueError("502: ZZ_SECRET backend body")
    logging.getLogger(f"{PREFIX}.pipeline").error("SOAP generation failed: %s", error)

    (_, props), = forwarded.events
    assert props["message"] == "SOAP generation failed: ValueError"


def test_a_path_argument_is_sent_as_its_file_name_only(forwarded):
    path = Path("/home/drsmith/.vetscribe/recordings/failed_1.wav")
    logging.getLogger(f"{PREFIX}.pipeline").error("audio saved to %s", path)

    (_, props), = forwarded.events
    assert props["message"] == "audio saved to failed_1.wav"


def test_tracebacks_are_never_sent(forwarded):
    try:
        raise ValueError("ZZ_SECRET")
    except ValueError:
        logging.getLogger(f"{PREFIX}.pipeline").exception("crashed")

    (_, props), = forwarded.events
    assert props["message"] == "crashed"
    assert "ZZ_SECRET" not in repr(forwarded.events)


def test_long_messages_are_capped(forwarded):
    logging.getLogger(f"{PREFIX}.pipeline").info("x" * 2000)

    (_, props), = forwarded.events
    assert len(props["message"]) == 500


def test_a_failing_capture_never_escapes_or_prints():
    handler = PostHogLogHandler(Capture(fail=True), prefix=PREFIX, loggers=("pipeline",))
    record = logging.LogRecord(f"{PREFIX}.pipeline", logging.INFO, __file__, 1, "hi", (), None)

    handler.handle(record)  # no exception


def test_the_local_record_is_left_untouched_for_the_other_handlers(forwarded):
    error = ValueError("full detail")
    record = logging.LogRecord(
        f"{PREFIX}.pipeline", logging.ERROR, __file__, 1, "failed: %s", (error,), None
    )

    logging.getLogger(f"{PREFIX}.pipeline").handle(record)

    assert record.args == (error,)
    assert record.getMessage() == "failed: full detail"
