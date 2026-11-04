"""The in-process bus (docs/backend.md 4.3)."""

import asyncio
import dataclasses
import time

import pytest

from dod import bus as events
from dod.bus import Bus, Event, PresetChanged, QueueJoined
from support import run, until


def preset(n):
    return PresetChanged(preset=f"p{n}", by="7f3a")


async def collect(sub, n, into):
    async for event in sub:
        into.append(event)
        if len(into) == n:
            return


# --- events -------------------------------------------------------------------


def test_every_event_from_the_design_exists():
    names = ["PresetChanged", "ParamChanged", "DrawingChanged", "SongStarted", "SongEnded", "TurnStarted",
             "TurnEnded", "QueueJoined", "QueueLeft", "BoardConnected", "BoardLost", "BoardLog", "BoardText",
             "BoardIncompatible", "LoadingStarted"]
    for name in names:
        cls = getattr(events, name)
        assert issubclass(cls, Event) and dataclasses.is_dataclass(cls), name


def test_events_are_frozen_keyword_only_and_stamped():
    before = time.time()
    e = PresetChanged(preset="fire", by="7f3a")
    assert before <= e.at <= time.time()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.preset = "rainbow"  # type: ignore[misc]
    with pytest.raises(TypeError):
        PresetChanged("fire", "7f3a")  # type: ignore[misc]
    assert PresetChanged(preset="fire", by=None, at=1.0) == PresetChanged(preset="fire", by=None, at=1.0)


def test_only_events_can_be_published():
    with pytest.raises(TypeError):
        Bus().publish("preset changed")  # type: ignore[arg-type]


# --- delivery -----------------------------------------------------------------


@run
async def test_two_listeners_get_every_event_in_order():
    bus = Bus()
    a, b = bus.subscribe(), bus.subscribe()
    got_a, got_b = [], []
    readers = asyncio.gather(collect(a, 50, got_a), collect(b, 50, got_b))
    sent = [preset(n) for n in range(50)]
    for event in sent:
        bus.publish(event)
        if event.preset.endswith("0"):
            await asyncio.sleep(0)  # let the readers run in between, too
    await asyncio.wait_for(readers, 2)
    assert got_a == sent and got_b == sent


@run
async def test_a_listener_gets_only_what_comes_after_subscribing():
    bus = Bus()
    bus.publish(preset(1))
    sub = bus.subscribe()
    bus.publish(preset(2))
    assert [e.preset for e in sub.take_all()] == ["p2"]


@run
async def test_publish_with_nobody_listening_is_fine():
    Bus().publish(preset(1))


@run
async def test_a_slow_listener_loses_its_oldest_and_counts_them():
    bus = Bus()
    slow = bus.subscribe(size=3)
    fast = bus.subscribe()
    got = []
    reader = asyncio.create_task(collect(fast, 1000, got))
    started = time.monotonic()
    for n in range(1000):
        bus.publish(preset(n))
        if n % 10 == 0:
            await asyncio.sleep(0)
    await asyncio.wait_for(reader, 2)
    # the fast one got everything, and the slow one didn't hold anybody up
    assert [e.preset for e in got] == [f"p{n}" for n in range(1000)]
    assert time.monotonic() - started < 1
    # the slow one kept only the newest three
    assert [e.preset for e in slow.take_all()] == ["p997", "p998", "p999"]
    assert slow.dropped == 997
    assert fast.dropped == 0


@run
async def test_a_waiting_listener_wakes_up():
    bus = Bus()
    sub = bus.subscribe()
    got = []
    reader = asyncio.create_task(collect(sub, 1, got))
    await asyncio.sleep(0.05)
    assert not got
    bus.publish(QueueJoined(session="7f3a", position=2))
    await asyncio.wait_for(reader, 1)
    assert got[0].position == 2


@run
async def test_take_all_doesnt_wait():
    bus = Bus()
    sub = bus.subscribe()
    assert sub.take_all() == []
    bus.publish(preset(1))
    bus.publish(preset(2))
    assert [e.preset for e in sub.take_all()] == ["p1", "p2"]
    assert sub.take_all() == []


# --- ending -------------------------------------------------------------------


@run
async def test_close_ends_the_iteration_and_stops_delivery():
    bus = Bus()
    sub = bus.subscribe()
    got = []
    reader = asyncio.create_task(collect(sub, 99, got))
    bus.publish(preset(1))
    await until(lambda: got, what="the first event")
    sub.close()
    await asyncio.wait_for(reader, 1)  # ended, although it wanted 99
    bus.publish(preset(2))
    assert len(got) == 1 and sub.take_all() == [] and sub.closed
    assert bus.listeners == 0
    sub.close()  # twice is fine


@run
async def test_with_block_closes():
    bus = Bus()
    with bus.subscribe() as sub:
        assert bus.listeners == 1
    assert sub.closed and bus.listeners == 0


@run
async def test_closing_the_bus_ends_every_subscription():
    bus = Bus()
    a, b = bus.subscribe(), bus.subscribe()
    readers = asyncio.gather(collect(a, 99, []), collect(b, 99, []))
    await asyncio.sleep(0.01)
    bus.close()
    await asyncio.wait_for(readers, 1)
    late = bus.subscribe()
    assert late.closed and [e async for e in late] == []
    bus.publish(preset(1))  # after shutdown: nobody gets it, nothing breaks


def test_size_must_be_positive():
    with pytest.raises(ValueError):
        Bus().subscribe(size=0)
