"""Live appointment events for the phone's ``GET /api/events`` stream.

The background worker (jobs.py) publishes one event when an uploaded recording
finishes processing, however it ended; every open stream gets a copy. Events
aren't persisted: a phone that wasn't listening catches up by re-reading the
appointments it's waiting on when it reconnects.

Publish and subscribe both run on the event loop (the worker publishes from
its own asyncio task), so the subscriber set needs no lock.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

DEFAULT_MAX_QUEUED = 100


class EventHub:
    def __init__(self, max_queued: int = DEFAULT_MAX_QUEUED):
        self._max_queued = max_queued
        self._subscribers: set[asyncio.Queue] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queued)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        for queue in self._subscribers:
            # A stream that stopped reading must never hold up the worker:
            # drop its oldest event instead (it catches up on reconnect anyway).
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
