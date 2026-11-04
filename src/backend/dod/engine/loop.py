"""The 30 fps render loop (docs/backend.md 7.1).

    every 1/30 s:
        picture = effect.render(ctx)
        out     = stage.apply(picture, now)
        hardware.show(out.hardware)
        every 3rd tick: on_preview(out.preview)

Fixed timestep on a monotonic clock: a late tick is just late, the next one
keeps its slot, and missed slots are skipped instead of rendered in a burst.
An effect that throws shows black for that tick; after 10 in a row the loop
falls back to idle, so one broken effect can't stop the show.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from dod.engine.effects.base import Context, Effect
from dod.engine.effects.idle import Idle
from dod.engine.output import HardwareFrame, OutputStage, PreviewFrame
from dod.engine.picture import MATRIX_ROWS, Picture

log = logging.getLogger(__name__)

FPS = 30
PREVIEW_EVERY = 3  # ticks: 10 previews a second
MAX_FAILURES = 10  # in a row, then idle
FPS_WINDOW = 2.0  # seconds the fps is measured over


class Display(Protocol):
    """What the loop needs from the hardware (dod.hardware.Hardware)."""

    @property
    def led_count(self) -> int: ...

    def show(self, frame: HardwareFrame) -> None: ...


@dataclass(frozen=True)
class Scene:
    """What to render: the effect, its parameters, and when it started (its t = 0).
    With a `drawing`, the 8x8 shows it instead of the effect's own picture."""

    effect: Effect
    params: Mapping[str, Any]
    started: float  # on the loop's clock
    drawing: bytes | None = None

DRAWING_BRIGHTNESS = 0.5  # for a drawing over an effect whose own 8x8 is dark


class RenderLoop:
    def __init__(self, display: Display, stage: OutputStage, *, effect: Effect | None = None,
                 params: Mapping[str, Any] | None = None, fps: float = FPS,
                 clock: Callable[[], float] = time.monotonic,
                 on_preview: Callable[[PreviewFrame], None] | None = None,
                 on_fallback: Callable[[str], None] | None = None) -> None:
        self.display = display
        self.stage = stage
        self.period = 1.0 / fps
        self.clock = clock
        self.on_preview = on_preview
        self.on_fallback = on_fallback  # called with the broken effect's id when the loop falls back to idle
        effect = effect or Idle()
        self.scene = Scene(effect, dict(params if params is not None else effect.defaults()), clock())
        self.ticks = 0
        self.last_output = None
        self._last_tick: float | None = None
        self._failures = 0
        self._errors_seen: set[str] = set()
        self._tick_times: deque[float] = deque()

    # --- what to show

    def set_effect(self, effect: Effect, params: Mapping[str, Any] | None = None) -> None:
        """A new effect; its time starts at 0."""
        self.scene = Scene(effect, dict(params if params is not None else effect.defaults()), self.clock(),
                           self.scene.drawing)
        self._failures = 0

    def set_params(self, params: Mapping[str, Any]) -> None:
        """New parameters for the running effect; its time goes on (a rainbow doesn't jump)."""
        s = self.scene
        self.scene = Scene(s.effect, dict(params), s.started, s.drawing)

    def set_drawing(self, drawing: bytes | None) -> None:
        """The visitor's drawing on the 8x8 (8 row bytes), or None for the effect's own."""
        if drawing is not None and len(drawing) != MATRIX_ROWS:
            raise ValueError(f"a drawing is {MATRIX_ROWS} rows")
        s = self.scene
        self.scene = Scene(s.effect, s.params, s.started, None if drawing is None else bytes(drawing))

    # --- running

    async def run(self) -> None:
        """Task: tick forever on a fixed timestep."""
        next_tick = self.clock()
        while True:
            self.tick(self.clock())
            next_tick += self.period
            now = self.clock()
            if next_tick < now:  # late by more than a tick: skip the missed slots, keep the phase
                next_tick += math.ceil((now - next_tick) / self.period) * self.period
            await asyncio.sleep(next_tick - now)

    def tick(self, now: float) -> None:
        """One frame. Never raises because of an effect."""
        dt = self.period if self._last_tick is None else now - self._last_tick
        self._last_tick = now
        scene = self.scene
        n = self.display.led_count
        drawing = scene.drawing if scene.drawing is not None else bytes(MATRIX_ROWS)
        picture = self._render(scene, Context(led_count=n, t=now - scene.started, dt=dt, params=scene.params,
                                              drawing=drawing), n)
        if scene.drawing is not None:
            picture = Picture(picture.leds, scene.drawing, picture.matrix_brightness or DRAWING_BRIGHTNESS)
        out = self.stage.apply(picture, now)
        self.display.show(out.hardware)
        self.last_output = out
        self.ticks += 1
        if self.on_preview is not None and self.ticks % PREVIEW_EVERY == 0:
            self.on_preview(out.preview)
        self._tick_times.append(now)
        while self._tick_times and self._tick_times[0] <= now - FPS_WINDOW:
            self._tick_times.popleft()

    @property
    def fps(self) -> float:
        """Ticks per second over the last two seconds."""
        return round(len(self._tick_times) / FPS_WINDOW, 1)

    def _render(self, scene: Scene, ctx: Context, n: int) -> Picture:
        try:
            picture = scene.effect.render(ctx)
            if picture.led_count != n:
                raise ValueError(f"rendered {picture.led_count} LEDs instead of {n}")
        except Exception as e:
            self._failed(scene.effect, e)
            return Picture.black(n)
        self._failures = 0
        return picture

    def _failed(self, effect: Effect, error: Exception) -> None:
        self._failures += 1
        message = f"{effect.id}: {type(error).__name__}: {error}"
        if message not in self._errors_seen and len(self._errors_seen) < 100:
            self._errors_seen.add(message)
            log.error("effect failed, showing black: %s", message, exc_info=error)
        if self._failures >= MAX_FAILURES and not isinstance(effect, Idle):
            log.error("effect %s failed %d times in a row; falling back to idle", effect.id, self._failures)
            self.set_effect(Idle())
            if self.on_fallback is not None:
                self.on_fallback(effect.id)
