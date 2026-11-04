"""The one state of the stand (docs/backend.md 6).

Everything a page shows: the mode, the preset and its parameters, the 8x8
drawing, what plays, the queue, the board's status. Commands change it
through methods; listeners are told once per change (the WebSocket hub
broadcasts the whole state, the render loop picks up the effect).

Who is who: visitors are public ids (dod.control.sessions), the main screen
is `MAIN`. Permissions (who may send what) are checked by the WebSocket
layer with may_control() before a command gets here; the methods here only
check that the values make sense, and raise ValueError when they don't.

Modes:

- manual: a preset runs. Picking a preset stops a song.
- music: a song plays. When it ends, back to the last preset.
- idle: nobody controls and nothing plays for `idle_seconds`. Any command ends it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from dod.bus import (
    Bus,
    DrawingChanged,
    Event,
    ParamChanged,
    PresetChanged,
    SongEnded,
    SongStarted,
)
from dod.control.queue import Queue
from dod.control.sessions import MAIN, short
from dod.engine.effects import PRESETS
from dod.engine.effects.base import Effect
from dod.settings import Settings

MODES = ("manual", "music", "idle")
MATRIX_MODES = ("icon", "drawing")
DRAWING = re.compile(r"[0-9a-f]{16}")
FIRST_PRESET = "rainbow"
# a song that ends by itself ends the controller's turn; one that is stopped doesn't
NATURAL_ENDS = ("ended", "overran", "player_gone")
SONG_END_REASONS = NATURAL_ENDS + ("stopped", "replaced")


@dataclass
class Song:
    song: str
    title: str
    length: float  # seconds
    started: float  # on the state's (monotonic) clock
    by: str


@dataclass
class _Manual:
    preset: str
    params: dict[str, dict[str, Any]] = field(default_factory=dict)  # per preset, remembered
    matrix: str = "icon"
    drawing: bytes = bytes(8)


class State:
    def __init__(self, settings: Settings, bus: Bus, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, presets: Mapping[str, type[Effect]] = PRESETS) -> None:
        self._bus = bus
        self._clock = clock
        self._wall = wall
        self._presets = dict(presets)
        self._idle_seconds = settings.idle_seconds
        self.queue = Queue(settings.turn_seconds, settings.inactive_seconds)
        self.mode = "idle"  # nobody plays yet
        first = FIRST_PRESET if FIRST_PRESET in self._presets else next(iter(self._presets))
        self._manual = _Manual(preset=first)
        self.song: Song | None = None
        self.player_connected = False
        self.hardware: dict[str, Any] = {"state": "connecting", "simulated": False, "fps": 0.0, "error": None}
        self._attended_at = clock()  # last moment someone controlled, something played, or a command came
        self._listeners: list[Callable[[State], None]] = []
        self._pending: list[Event] = []
        self._depth = 0

    # --- listening

    def on_change(self, listener: Callable[[State], None]) -> None:
        """`listener(state)` is called once after every change."""
        self._listeners.append(listener)

    @contextmanager
    def _change(self) -> Iterator[None]:
        """Around every public method: events go to the bus, listeners hear of a
        change once, and only if something really changed."""
        outer = self._depth == 0
        before = self._signature() if outer else None
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
        if outer:
            events, self._pending = self._pending, []
            for event in events:
                self._bus.publish(event)
            if self._signature() != before:
                for listener in list(self._listeners):
                    listener(self)

    def _signature(self) -> tuple[Any, ...]:
        m, s, q = self._manual, self.song, self.queue
        return (
            self.mode, m.preset, tuple(sorted(self.params.items())), m.matrix, m.drawing,
            (s.song, s.started) if s else None, self.player_connected,
            q.controller, q.turn_ends_at, q.waiting, q.paused, q.turn_over,
            tuple(sorted(self.hardware.items())),
        )

    def _emit(self, events: list[Event]) -> None:
        self._pending.extend(events)

    # --- reading

    @property
    def preset(self) -> str:
        return self._manual.preset

    @property
    def params(self) -> dict[str, Any]:
        """The current preset's parameters."""
        return self._params_of(self._manual.preset)

    @property
    def matrix_mode(self) -> str:
        return self._manual.matrix

    @property
    def drawing(self) -> bytes:
        return self._manual.drawing

    @property
    def playing(self) -> bool:
        return self.song is not None

    def may_control(self, who: str) -> bool:
        """Presets, parameters, the drawing, songs: the controller and the main screen."""
        return who == MAIN or who == self.queue.controller

    def _params_of(self, preset: str) -> dict[str, Any]:
        stored = self._manual.params.get(preset)
        return dict(stored) if stored is not None else self._presets[preset].defaults()

    # --- commands that change what the stand shows

    def set_preset(self, preset: str, by: str) -> None:
        if preset not in self._presets:
            raise ValueError(f"unknown preset {preset!r}")
        with self._change():
            self._command(by)
            if self.song is not None:
                self._end_song("stopped")
            changed = preset != self._manual.preset or self.mode != "manual"
            self._manual.preset = preset
            self.mode = "manual"
            if changed:
                self._emit([PresetChanged(preset=preset, by=short(by))])

    def set_param(self, name: str, value: Any, by: str) -> None:
        """For the current preset. While a song plays it is remembered for when the song ends."""
        preset = self._manual.preset
        checked = self._presets[preset].check_param(name, value)
        with self._change():
            self._command(by)
            if self.mode == "idle":
                self.mode = "manual"
            params = self._params_of(preset)
            if params.get(name) != checked:
                params[name] = checked
                self._manual.params[preset] = params
                self._emit([ParamChanged(preset=preset, name=name, value=checked, by=short(by))])

    def set_matrix(self, mode: str, drawing: str | None, by: str) -> None:
        """`mode` 'icon' or 'drawing'; `drawing` 8 rows as 16 hex characters, or None to keep it."""
        if mode not in MATRIX_MODES:
            raise ValueError(f"matrix mode must be icon or drawing, got {mode!r}")
        if drawing is not None and not (isinstance(drawing, str) and DRAWING.fullmatch(drawing.lower())):
            raise ValueError("drawing must be 16 hex characters (8 rows)")
        with self._change():
            self._command(by)
            if self.mode == "idle":
                self.mode = "manual"
            self._manual.matrix = mode
            if drawing is not None and bytes.fromhex(drawing) != self._manual.drawing:
                self._manual.drawing = bytes.fromhex(drawing)
                self._emit([DrawingChanged(by=short(by))])

    # --- songs (the player, plan step 8, decides when; the state keeps the mode right)

    def song_started(self, song: str, title: str, length: float, by: str) -> None:
        with self._change():
            self._command(by)
            if self.song is not None:
                self._end_song("replaced")
            now = self._clock()
            self.song = Song(song=song, title=title, length=length, started=now, by=by)
            self.mode = "music"
            self.queue.song_started(by, now)
            self._emit([SongStarted(song=song, title=title, by=short(by))])

    def song_ended(self, reason: str) -> None:
        """`reason`: 'ended', 'overran', 'player_gone' (it ended by itself), or
        'stopped', 'replaced' (someone picked something else)."""
        if reason not in SONG_END_REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        with self._change():
            if self.song is not None:
                self._end_song(reason)
                self.mode = "manual"

    def _end_song(self, reason: str) -> None:
        assert self.song is not None
        song, self.song = self.song, None
        now = self._clock()
        self._attended_at = now
        self._emit([SongEnded(song=song.song, reason=reason)])
        if reason in NATURAL_ENDS:
            self._emit(self.queue.song_ended(now))
        else:
            self.queue.song_stopped(now)

    def set_player_connected(self, connected: bool) -> None:
        with self._change():
            self.player_connected = connected

    # --- the queue

    def join(self, who: str) -> None:
        with self._change():
            self._emit(self.queue.join(who, self._clock()))

    def leave(self, who: str) -> None:
        with self._change():
            self._emit(self.queue.leave(who, self._clock()))

    def connected(self, who: str) -> None:
        with self._change():
            self.queue.connected(who, self._clock())

    def disconnected(self, who: str) -> None:
        with self._change():
            self.queue.disconnected(who, self._clock())

    def skip(self) -> None:
        with self._change():
            self._emit(self.queue.skip(self._clock()))

    def pause_queue(self) -> None:
        with self._change():
            self.queue.pause(self._clock())

    def resume_queue(self) -> None:
        with self._change():
            self._emit(self.queue.resume(self._clock()))

    # --- the clock, the board, the engine

    def tick(self) -> None:
        """A few times a second (the queue clock task): turns, and idle mode."""
        with self._change():
            now = self._clock()
            # attended up to now if someone controlled until this tick (before the queue may end the turn)
            if self.queue.controller is not None or self.song is not None:
                self._attended_at = now
            self._emit(self.queue.tick(now))
            if self.queue.controller is not None or self.song is not None:
                self._attended_at = now
            elif self.mode != "idle" and now - self._attended_at >= self._idle_seconds:
                self.mode = "idle"

    def set_hardware(self, part: Mapping[str, Any]) -> None:
        """The board's status for the pages (Hardware's on_status)."""
        with self._change():
            self.hardware = dict(part)

    def effect_failed(self, effect_id: str) -> None:
        """The render loop gave up on an effect and shows idle; the state follows."""
        with self._change():
            if self.mode == "manual" and self._manual.preset == effect_id:
                self.mode = "idle"

    def _command(self, by: str) -> None:
        now = self._clock()
        self._attended_at = now
        self.queue.activity(by, now)

    # --- for the pages

    def to_dict(self) -> dict[str, Any]:
        """The state message's content (docs/backend.md 6), times on the wall clock."""
        wall_now, now = self._wall(), self._clock()

        def wall(t: float | None) -> float | None:
            return None if t is None else round(wall_now + (t - now), 3)

        s, q, m = self.song, self.queue, self._manual
        return {
            "now": round(wall_now, 3),
            "mode": self.mode,
            "manual": {"preset": m.preset, "params": self.params, "matrix": m.matrix, "drawing": m.drawing.hex()},
            "music": {
                "song": s.song if s else None,
                "title": s.title if s else None,
                "started_at": wall(s.started) if s else None,
                "length": s.length if s else None,
                "playing": s is not None,
                "player_connected": self.player_connected,
            },
            "queue": {
                "controller": short(q.controller),
                "turn_ends_at": wall(q.turn_ends_at),
                "turn_over": q.turn_over,
                "waiting": len(q.waiting),
                "paused": q.paused,
            },
            "hardware": dict(self.hardware),
        }

    def you(self, who: str) -> dict[str, Any]:
        """The `you` message for one browser: where it is in the queue."""
        position = self.queue.position(who)
        in_control = position == 0
        ends = self.queue.turn_ends_at if in_control else None
        return {
            "session": short(who),
            "position": position,
            "in_control": in_control,
            "turn_ends_at": None if ends is None else round(self._wall() + (ends - self._clock()), 3),
        }
