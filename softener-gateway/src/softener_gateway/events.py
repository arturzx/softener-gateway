from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    timestamp: datetime = field(default_factory=datetime.now)


class _ClosedSubscription:
    pass


_CLOSED_SUBSCRIPTION = _ClosedSubscription()
EventEnvelope = tuple[object, Event]


class Subscription:
    def __init__(
        self,
        event_bus: EventBus,
        event_types: tuple[type[Event], ...],
    ) -> None:
        self._event_bus = event_bus
        self._event_types = event_types
        self._queue: asyncio.Queue[EventEnvelope | _ClosedSubscription] = asyncio.Queue()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> EventEnvelope:
        if self._closed and self._queue.empty():
            raise StopAsyncIteration

        item = await self._queue.get()
        if isinstance(item, _ClosedSubscription):
            raise StopAsyncIteration

        return item

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._event_bus._remove(self)
        self._clear_queue()
        self._queue.put_nowait(_CLOSED_SUBSCRIPTION)

    def _publish(self, emitter: object, event: Event) -> None:
        if not self._closed:
            self._queue.put_nowait((emitter, event))

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self, *event_types: type[Event]) -> Subscription:
        subscription = Subscription(self, event_types)
        self._subscribers.add(subscription)
        return subscription

    async def publish(self, emitter: object, event: Event) -> None:
        for subscription in tuple(self._subscribers):
            if self._matches(subscription, event):
                subscription._publish(emitter, event)

    def _remove(self, subscription: Subscription) -> None:
        self._subscribers.discard(subscription)

    def _matches(self, subscription: Subscription, event: Event) -> bool:
        return not subscription._event_types or isinstance(event, subscription._event_types)


__all__ = ["Event", "EventBus", "EventEnvelope", "Subscription"]
