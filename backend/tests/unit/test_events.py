"""EventHub: fan-out of appointment events to every open /api/events stream."""

import asyncio

from vet_soap_notetaker_backend.events import EventHub


async def test_publish_reaches_every_subscriber():
    hub = EventHub()
    async with hub.subscribe() as first, hub.subscribe() as second:
        hub.publish({"id": "a1"})
        assert await asyncio.wait_for(first.get(), 1) == {"id": "a1"}
        assert await asyncio.wait_for(second.get(), 1) == {"id": "a1"}


async def test_a_closed_subscription_gets_nothing_more():
    hub = EventHub()
    async with hub.subscribe() as queue:
        pass
    hub.publish({"id": "a1"})
    assert queue.empty()
    assert hub.subscriber_count == 0


async def test_publish_with_no_subscribers_is_a_no_op():
    EventHub().publish({"id": "a1"})


async def test_a_slow_subscriber_drops_its_oldest_events_rather_than_blocking():
    hub = EventHub(max_queued=2)
    async with hub.subscribe() as queue:
        for n in range(3):
            hub.publish({"n": n})
        assert [queue.get_nowait(), queue.get_nowait()] == [{"n": 1}, {"n": 2}]
