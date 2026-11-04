"""The fake log generator (docs/backend.md 10): it decides when lines are
written and sends them to the hub in batches. What they say is in
dod.logs.templates.

    gen = LogGenerator(bus, send=hub.send_log, facts=read_facts)   # listens from here on
    tasks.start("log generator", gen.run)
    hub gets gen.history, so a page that connects starts with a full screen

Every step (20 a second, so at most 20 batches a second):

- real events from the bus become lines right away; parameter and drawing
  changes at most one line per THROTTLE seconds each (a dragged slider sends
  20 a second), with the latest value
- filler: every second 3-8 lines at spread-out moments
- LoadingStarted and SongStarted start a burst of 30-50 lines over 1-2 s;
  filler pauses meanwhile. At most one burst every BURST_GAP seconds for the
  whole stand; a trigger in between is dropped, not saved for later
- the last HISTORY lines are kept

step(now) does all of it for one moment, with no waiting, so tests drive it
with a fake clock.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from dod.api.messages import LogLine
from dod.bus import Bus, DrawingChanged, Event, LoadingStarted, ParamChanged, SongStarted
from dod.logs import templates
from dod.logs.templates import Facts, Line

log = logging.getLogger(__name__)

STEP_SECONDS = 0.05  # 20 batches a second at most
CALM_MIN, CALM_MAX = 3, 8  # filler lines a second
BURST_GAP = 3.0  # seconds between the starts of two bursts, at least
BURST_SECONDS = (1.0, 1.8)  # how long a burst takes
THROTTLE = 0.5  # seconds between two lines for the same parameter (or the drawing)
HISTORY = 300


@dataclass
class _Throttled:
    last: float  # when its last line was written
    pending: Event | None = None  # a newer event, written when THROTTLE has passed


class LogGenerator:
    def __init__(self, bus: Bus, *, send: Callable[[list[LogLine]], None],
                 facts: Callable[[], Facts] = Facts, rng: random.Random | None = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        self._sub = bus.subscribe()  # now, so nothing published after this is missed
        self._send = send
        self._facts = facts
        self._rng = rng or random.Random()
        self._clock = clock
        # one wall time read at start; line times follow the monotonic clock from
        # there, so they never go backwards (and a fake clock moves them too)
        self._wall0, self._clock0 = wall(), clock()
        self._history: deque[LogLine] = deque(maxlen=HISTORY)
        self._filler_at: deque[float] = deque()  # when the planned filler lines are due
        self._planned_until: float | None = None  # filler is planned up to here
        self._burst: deque[tuple[float, Line]] = deque()  # (due, line), in order
        self._burst_ends = float("-inf")
        self._last_burst: float | None = None
        self._throttled: dict[tuple[str, ...], _Throttled] = {}
        self._broken: set[str] = set()  # templates that raised, logged once each
        self.bursts = 0  # started so far

    # --- the task

    async def run(self) -> None:
        """Task: a step every STEP_SECONDS."""
        while True:
            self.step(self._clock())
            await asyncio.sleep(STEP_SECONDS)

    def history(self) -> list[LogLine]:
        """The last HISTORY lines, oldest first: for a page that just connected."""
        return list(self._history)

    def close(self) -> None:
        self._sub.close()

    # --- one step

    def step(self, now: float) -> list[LogLine]:
        """Everything due by `now`, sent as one batch (nothing is sent when there
        is nothing). Returns the batch."""
        facts = self._read_facts()
        lines: list[Line] = []
        for event in self._sub.take_all():
            lines += self._on_event(event, now, facts)
        lines += self._due_throttled(now)
        while self._burst and self._burst[0][0] <= now:
            lines.append(self._burst.popleft()[1])
        lines += self._due_filler(now, facts)
        if not lines:
            return []
        batch = [LogLine(t=self._wall(now), tag=tag, level=level, text=text) for tag, level, text in lines]
        self._history.extend(batch)
        self._send(batch)
        return batch

    def _wall(self, now: float) -> float:
        return round(self._wall0 + (now - self._clock0), 3)

    def _read_facts(self) -> Facts:
        try:
            return self._facts()
        except Exception:  # a bug in what reads them; the filler goes on without real numbers
            self._once("facts", "reading the facts for the logs failed")
            return Facts()

    # --- real events

    def _on_event(self, event: Event, now: float, facts: Facts) -> list[Line]:
        if isinstance(event, LoadingStarted):
            self._start_burst("loading", now, facts)
            return []
        key = self._throttle_key(event)
        if key is not None:
            slot = self._throttled.get(key)
            if slot is not None and now - slot.last < THROTTLE:
                slot.pending = event
                return []
            self._throttled[key] = _Throttled(last=now)
        lines = self._lines_for(event)
        if isinstance(event, SongStarted):
            self._start_burst("song", now, facts)
        return lines

    @staticmethod
    def _throttle_key(event: Event) -> tuple[str, ...] | None:
        match event:
            case ParamChanged(preset=preset, name=name):
                return ("param", preset, name)
            case DrawingChanged():
                return ("drawing",)
        return None

    def _due_throttled(self, now: float) -> list[Line]:
        lines: list[Line] = []
        for slot in self._throttled.values():
            if slot.pending is not None and now - slot.last >= THROTTLE:
                lines += self._lines_for(slot.pending)
                slot.pending, slot.last = None, now
        return lines

    def _lines_for(self, event: Event) -> list[Line]:
        try:
            return templates.event_lines(event)
        except Exception:
            self._once(type(event).__name__, f"no log line for {type(event).__name__}")
            return []

    # --- bursts

    def _start_burst(self, kind: str, now: float, facts: Facts) -> None:
        if self._last_burst is not None and now - self._last_burst < BURST_GAP:
            return  # one every BURST_GAP for the whole stand
        try:
            lines = templates.burst(kind, self._rng, facts)
        except Exception:
            self._once(f"burst {kind}", f"the {kind} burst failed")
            return
        self._last_burst = now
        self.bursts += 1
        length = self._rng.uniform(*BURST_SECONDS)
        offsets = sorted(self._rng.uniform(0, length) for _ in lines)
        offsets[0], offsets[-1] = 0.0, length  # starts now, takes the whole length
        self._burst = deque((now + offset, line) for offset, line in zip(offsets, lines))
        self._burst_ends = now + length

    # --- filler

    def _due_filler(self, now: float, facts: Facts) -> list[Line]:
        if self._planned_until is None or now - self._planned_until > 1.0:
            # the first step, or the process was stalled: plan from now, don't catch up
            self._filler_at.clear()
            self._planned_until = now
        while self._planned_until <= now:
            self._plan_second(self._planned_until)
            self._planned_until += 1.0
        lines: list[Line] = []
        while self._filler_at and self._filler_at[0] <= now:
            due = self._filler_at.popleft()
            if due < self._burst_ends:
                continue  # a burst is running: its lines are the filler
            lines.append(self._filler(facts))
        return lines

    def _plan_second(self, start: float) -> None:
        """3-8 lines in the second from `start`, one in each equal slice of it, so
        they don't bunch up."""
        n = self._rng.randint(CALM_MIN, CALM_MAX)
        self._filler_at.extend(start + (i + self._rng.random()) / n for i in range(n))

    def _filler(self, facts: Facts) -> Line:
        try:
            return templates.filler(self._rng, facts)
        except Exception:
            self._once("filler", "a filler template failed")
            return "sched", "DEBUG", "tick"

    def _once(self, key: str, message: str) -> None:
        """A bug in the generator goes to the real log once, never to the terminal."""
        if key not in self._broken:
            self._broken.add(key)
            log.exception(message)
