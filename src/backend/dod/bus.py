"""In-process events: who did what (docs/backend.md 4.3).

Features publish what happened; whoever cares subscribes. So the log
generator can turn "preset changed" into log lines without the preset code
knowing that logs exist.

    bus.publish(PresetChanged(preset="fire", by="7f3a"))

    sub = bus.subscribe()          # listening from now on, before anything is awaited
    async for event in sub: ...

Every subscriber has its own queue. A slow one loses its oldest events (and
counts them in `dropped`); publish() never waits, so nobody is slowed down.

publish() must be called from the event loop's thread. From another thread
(the song downloader): `loop.call_soon_threadsafe(bus.publish, event)`.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Self

DEFAULT_QUEUE = 256


# --- events -------------------------------------------------------------------
# `by` is who caused it: a session's short id, "main" for the main screen, or
# None for the backend itself. `session` is a public id (dod.control.sessions),
# never the secret cookie. `at` is wall-clock time, for the log lines.


@dataclass(frozen=True, kw_only=True)
class Event:
    at: float = field(default_factory=time.time)


@dataclass(frozen=True, kw_only=True)
class PresetChanged(Event):
    preset: str
    by: str | None


@dataclass(frozen=True, kw_only=True)
class ParamChanged(Event):
    preset: str
    name: str
    value: object
    by: str | None


@dataclass(frozen=True, kw_only=True)
class DrawingChanged(Event):
    by: str | None


@dataclass(frozen=True, kw_only=True)
class SongStarted(Event):
    song: str
    title: str
    by: str | None


@dataclass(frozen=True, kw_only=True)
class SongEnded(Event):
    song: str
    reason: str  # "ended", "overran", "player_gone", "stopped", "replaced"


@dataclass(frozen=True, kw_only=True)
class TurnStarted(Event):
    session: str
    waiting: int


@dataclass(frozen=True, kw_only=True)
class TurnEnded(Event):
    session: str
    reason: str  # "time", "song", "inactive", "left", "skipped"


@dataclass(frozen=True, kw_only=True)
class QueueJoined(Event):
    session: str
    position: int


@dataclass(frozen=True, kw_only=True)
class QueueLeft(Event):
    session: str
    reason: str = "left"  # "left", or "gone": offline too long while waiting


@dataclass(frozen=True, kw_only=True)
class BoardConnected(Event):
    led_count: int
    firmware: str
    simulated: bool
    rebooted: bool


@dataclass(frozen=True, kw_only=True)
class BoardLost(Event):
    reason: str


@dataclass(frozen=True, kw_only=True)
class BoardLog(Event):
    level: str  # "DEBUG", "INFO", "WARN", "ERROR"
    text: str


@dataclass(frozen=True, kw_only=True)
class BoardText(Event):
    line: str


@dataclass(frozen=True, kw_only=True)
class BoardIncompatible(Event):
    reason: str
    protocol: int


@dataclass(frozen=True, kw_only=True)
class LoadingStarted(Event):
    by: str | None


# --- the bus ------------------------------------------------------------------


class Subscription:
    """One listener's queue. Iterate it, or take what is there with take_all()."""

    def __init__(self, bus: Bus, size: int) -> None:
        self._bus = bus
        self._items: deque[Event] = deque()
        self._size = size
        self._ready = asyncio.Event()
        self._closed = False
        self.dropped = 0  # events lost because this listener fell behind

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Event:
        while not self._items:
            if self._closed:
                raise StopAsyncIteration
            self._ready.clear()
            await self._ready.wait()
        return self._items.popleft()

    def take_all(self) -> list[Event]:
        """Everything queued, without waiting; for listeners that run on their own clock."""
        items = list(self._items)
        self._items.clear()
        return items

    def close(self) -> None:
        """Stop listening. Iteration ends; queued events are discarded."""
        if self._closed:
            return
        self._closed = True
        self._items.clear()
        self._bus._subs.discard(self)
        self._ready.set()

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _offer(self, event: Event) -> None:
        if len(self._items) >= self._size:
            self._items.popleft()
            self.dropped += 1
        self._items.append(event)
        self._ready.set()


class Bus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._closed = False

    def publish(self, event: Event) -> None:
        """Hand the event to every subscriber. Never waits."""
        if not isinstance(event, Event):
            raise TypeError(f"publish() takes an Event, got {type(event).__name__}")
        for sub in tuple(self._subs):
            sub._offer(event)

    def subscribe(self, size: int = DEFAULT_QUEUE) -> Subscription:
        """A new listener. It gets every event published from now on, and
        keeps up to `size` unread ones."""
        if size < 1:
            raise ValueError("size must be at least 1")
        sub = Subscription(self, size)
        if self._closed:
            sub._closed = True
        else:
            self._subs.add(sub)
        return sub

    @property
    def listeners(self) -> int:
        return len(self._subs)

    def close(self) -> None:
        """At shutdown: every subscription ends; later ones end right away."""
        self._closed = True
        for sub in tuple(self._subs):
            sub.close()
