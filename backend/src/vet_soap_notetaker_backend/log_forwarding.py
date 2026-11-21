"""Forward a scrubbed copy of chosen log lines to PostHog as ``diagnostic_log`` events.

So a misbehaving inject at a clinic can be diagnosed remotely, the lines that
explain *how* it went (provider failures and retries, async job outcomes) go
to PostHog too, tagged by ``capture`` with the app, environment and
clinic. Only the listed loggers at INFO and above are sent, and each line is
scrubbed first: an exception argument becomes just its type name (an
``ApiClientError``'s text carries backend bodies), a path becomes just its file
name (no ``C:\\Users\\<name>``), tracebacks are dropped and the message is capped.
The local log file is untouched and keeps the full detail.

The PostHog Python SDK has no logs API, so lines go as ordinary events: the
same batching thread, never blocking or raising into the caller.
"""

import logging
import os
import threading

MAX_MESSAGE_CHARS = 500


def _scrub_arg(value):
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, os.PathLike):
        return os.path.basename(os.fspath(value))
    return value


class PostHogLogHandler(logging.Handler):
    def __init__(self, capture, prefix: str, loggers, level=logging.INFO):
        super().__init__(level)
        self._capture = capture
        self._prefix = prefix
        self._loggers = tuple(loggers)
        self._busy = threading.local()

    def _short_name(self, name: str) -> str | None:
        if not name.startswith(self._prefix + "."):
            return None
        short = name[len(self._prefix) + 1:]
        if any(short == listed or short.startswith(listed + ".") for listed in self._loggers):
            return short
        return None

    def emit(self, record: logging.LogRecord) -> None:
        short = self._short_name(record.name)
        # Re-entrancy guard: a capture that itself logs must not loop.
        if short is None or getattr(self._busy, "active", False):
            return
        self._busy.active = True
        try:
            args = record.args
            if isinstance(args, tuple):
                args = tuple(_scrub_arg(a) for a in args)
            elif isinstance(args, dict):
                args = {k: _scrub_arg(v) for k, v in args.items()}
            message = str(record.msg) % args if args else str(record.msg)
            self._capture(
                "diagnostic_log",
                {
                    "logger": short,
                    "level": record.levelname,
                    "message": message[:MAX_MESSAGE_CHARS],
                },
            )
        except Exception:
            pass  # forwarding is best-effort; never break (or spam) the app's logging
        finally:
            self._busy.active = False

    def handleError(self, record) -> None:
        pass


def install(logger: logging.Logger, handler: PostHogLogHandler) -> None:
    """Attach ``handler``, replacing any forwarding handler attached before (a
    rebuilt app, or a test building several), so lines are never sent twice."""
    for existing in [h for h in logger.handlers if isinstance(h, PostHogLogHandler)]:
        logger.removeHandler(existing)
    logger.addHandler(handler)
