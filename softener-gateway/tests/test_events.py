import asyncio
from dataclasses import dataclass
from datetime import datetime

import pytest

from softener_gateway.events import Event, EventBus, Subscription


@dataclass(frozen=True, slots=True)
class FakeEvent(Event):
    value: int


@dataclass(frozen=True, slots=True)
class OtherEvent(Event):
    value: str


def test_event_sets_timestamp_automatically() -> None:
    before = datetime.now()
    event = FakeEvent(value=1)
    after = datetime.now()

    assert before <= event.timestamp <= after


def test_event_accepts_explicit_timestamp() -> None:
    timestamp = datetime(2026, 7, 5, 12, 0, 0)

    event = FakeEvent(value=1, timestamp=timestamp)

    assert event.timestamp == timestamp


def test_event_bus_broadcasts_event_to_each_subscription() -> None:
    asyncio.run(_broadcast_event())


async def _broadcast_event() -> None:
    event_bus = EventBus()
    first = event_bus.subscribe()
    second = event_bus.subscribe()
    emitter = object()
    event = FakeEvent(value=1)

    await event_bus.publish(emitter, event)

    assert await anext(first) == (emitter, event)
    assert await anext(second) == (emitter, event)


def test_event_bus_filters_subscription_by_event_type() -> None:
    asyncio.run(_filter_subscription_by_event_type())


async def _filter_subscription_by_event_type() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(FakeEvent)
    emitter = object()
    skipped = OtherEvent(value="skipped")
    received = FakeEvent(value=1)

    await event_bus.publish(emitter, skipped)
    await event_bus.publish(emitter, received)

    assert await anext(subscription) == (emitter, received)


def test_event_bus_accepts_multiple_event_filter_types() -> None:
    asyncio.run(_filter_subscription_by_multiple_event_types())


async def _filter_subscription_by_multiple_event_types() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(FakeEvent, OtherEvent)
    emitter = object()
    first = FakeEvent(value=1)
    second = OtherEvent(value="second")

    await event_bus.publish(emitter, first)
    await event_bus.publish(emitter, second)

    assert await anext(subscription) == (emitter, first)
    assert await anext(subscription) == (emitter, second)


def test_subscription_close_removes_queue_from_event_bus() -> None:
    asyncio.run(_close_subscription())


async def _close_subscription() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe()

    subscription.close()
    await event_bus.publish(object(), FakeEvent(value=1))

    assert event_bus.subscriber_count == 0
    assert subscription.is_closed
    with pytest.raises(StopAsyncIteration):
        await anext(subscription)


def test_subscription_is_async_context_manager() -> None:
    asyncio.run(_use_subscription_as_async_context_manager())


async def _use_subscription_as_async_context_manager() -> None:
    event_bus = EventBus()

    async with event_bus.subscribe() as subscription:
        assert event_bus.subscriber_count == 1
        assert not subscription.is_closed

    assert event_bus.subscriber_count == 0
    assert subscription.is_closed


def test_subscription_is_async_iterator() -> None:
    asyncio.run(_use_subscription_as_async_iterator())


async def _use_subscription_as_async_iterator() -> None:
    event_bus = EventBus()
    emitter = object()
    event = FakeEvent(value=1)

    async with event_bus.subscribe() as subscription:
        await event_bus.publish(emitter, event)

        received_emitter, received = await _read_one(subscription)

    assert received_emitter is emitter
    assert received is event


async def _read_one(subscription: Subscription) -> tuple[object, Event]:
    async for emitter, event in subscription:
        return emitter, event

    raise AssertionError("subscription ended before event was received")


def test_subscription_shutdown_wakes_pending_iterator() -> None:
    asyncio.run(_wake_pending_iterator())


async def _wake_pending_iterator() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe()

    task = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)

    subscription.close()

    with pytest.raises(StopAsyncIteration):
        await task
