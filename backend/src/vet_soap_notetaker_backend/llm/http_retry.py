"""Shared retry wrapper for the provider HTTP calls.

The LLM providers all make a single blocking ``httpx.post`` and then
``raise_for_status()``. Two transient failure modes are worth retrying rather
than surfacing to the vet as a dead "note generation failed":

* transport-level errors -- timeouts (a slow transcription of a long clip),
  connection resets, DNS blips; and
* ``429`` / ``5xx`` responses -- the provider being momentarily rate-limited or
  overloaded.

Deterministic ``4xx`` failures (``400`` bad request, ``401``/``403`` bad key) are
*not* retried: the same request will fail the same way, so retrying only delays
the error. ``post_with_retries`` centralises this so every provider gets the same
behaviour instead of each re-implementing it.
"""

import time

import httpx

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    # Every httpx.RequestError is a transport-level failure (timeout, connect
    # error, read error, ...) -- all transient and worth another attempt.
    return isinstance(exc, httpx.RequestError)


def post_with_retries(
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    **post_kwargs,
) -> httpx.Response:
    """POST (with ``raise_for_status``), retrying transient failures with backoff.

    Makes up to ``max_retries`` retries after the first attempt (so at most
    ``max_retries + 1`` requests). The delay before the Nth retry is
    ``backoff_base_seconds * 2 ** (N - 1)`` -- i.e. 1s, 2s, 4s with the defaults.
    All other keyword arguments are forwarded straight to ``httpx.post``.
    """
    attempt = 0
    while True:
        try:
            response = httpx.post(**post_kwargs)
            response.raise_for_status()
            return response
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            time.sleep(backoff_base_seconds * 2**attempt)
            attempt += 1
