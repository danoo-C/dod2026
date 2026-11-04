"""The FastAPI app and its lifespan (docs/backend.md 4.1).

create_app() builds a new app; nothing is created at import time, so every
test gets its own app. uvicorn calls it with `--factory`. The lifespan is the
only place that creates the backend's parts and connects them.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from dod import hardware
from dod.api import http, ws
from dod.api.ws import Hub
from dod.bus import Bus
from dod.engine.effects import PRESETS
from dod.engine.effects.base import Effect
from dod.engine.effects.idle import Idle
from dod.engine.effects.rainbow import Rainbow
from dod.engine.loop import RenderLoop
from dod.engine.output import OutputStage
from dod.logs.generator import LogGenerator
from dod.logs.templates import Facts
from dod.settings import Settings, SettingsError
from dod.state import State
from dod.tasks import Supervisor

log = logging.getLogger("dod")

QUEUE_CLOCK_SECONDS = 0.25  # the queue clock: 4 ticks a second

LOG_FORMATS = {
    "dod": "%(levelname)-9s %(name)s: %(message)s",  # lines up with uvicorn's "INFO:     ..."
    "hcl": "%(levelname)-9s %(message)s",  # the HCL's messages already start with "hcl: "
}


def create_app(settings: Settings | None = None, *, link: Any = None,
               restart_seconds: float | None = None) -> FastAPI:
    """The app. Without `settings`, they are read from the environment, and a
    wrong one stops the process with a message naming the variable.

    `link` replaces the link to the board from DOD_SERIAL (tests pass one from
    hcl.testing.sim_link()); main.py never imports hcl itself.
    """
    if settings is None:
        settings = settings_or_exit()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 1.-2. the parts that don't need anything else
        bus = Bus()
        state = State(settings, bus)
        # the fake logs listen from the start, so the board's first events make it in;
        # hub, hw and loop are created below, before the generator's task runs
        logs = LogGenerator(bus, send=lambda lines: hub.send_log(lines),
                            facts=lambda: log_facts(hw, loop, state, hub))
        # 3. the hardware: connecting runs in the background, nothing waits for it
        hw = hardware.Hardware(link if link is not None else hardware.open_link(settings), bus,
                               fallback_led_count=settings.led_count,
                               simulated=hardware.is_simulated(settings.serial),
                               on_status=lambda status: state.set_hardware(status.for_pages()))
        state.set_hardware(hw.status.for_pages())
        await hw.start()
        # the browsers' hub, so the engine can send it previews
        hub = Hub(state, bus, settings, songs=app.state.songs, log_history=logs.history)
        state.on_change(hub.state_changed)
        # 4. the engine, following the state
        stage = OutputStage(brightness=settings.brightness, power_limit_ma=settings.power_limit_ma)
        loop = RenderLoop(hw, stage, effect=Idle(), on_fallback=state.effect_failed, on_preview=hub.preview)
        state.on_change(SceneSync(loop))
        # 5. the background tasks
        tasks = Supervisor() if restart_seconds is None else Supervisor(restart_seconds)
        tasks.start("render loop", loop.run)
        tasks.start("hcl events", hw.run_events)
        tasks.start("status poller", hw.poll_status)
        tasks.start("queue clock", lambda: queue_clock(state))
        tasks.start("state broadcaster", hub.run)
        tasks.start("log generator", logs.run)
        app.state.bus, app.state.state, app.state.hardware = bus, state, hw
        app.state.logs = logs
        app.state.loop, app.state.tasks, app.state.hub = loop, tasks, hub
        # 6. where the internal pages are
        log.info("main screen:  %s/internal/main?key=%s", settings.public_url, settings.internal_key)
        log.info("logging page: %s/internal/logging?key=%s", settings.public_url, settings.internal_key)
        try:
            yield  # 7. serve
        finally:
            hub.close_all()  # no new WebSockets, the open ones closed
            # in reverse; the last frame is not blanked: the board shows its own
            # idle animation 3 s after the frames stop (hcl.md 7.2)
            await tasks.stop()
            await hw.stop()
            bus.close()

    app = FastAPI(title="DOD 2026", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.songs = lambda: []  # the song list (plan step 8)
    app.include_router(http.router)
    app.include_router(ws.router)
    return app


async def queue_clock(state: State) -> None:
    """Task: turns end and idle mode starts even when nobody sends anything."""
    while True:
        state.tick()
        await asyncio.sleep(QUEUE_CLOCK_SECONDS)


def log_facts(hw: hardware.Hardware, loop: RenderLoop, state: State, hub: Hub) -> Facts:
    """The real numbers for the fake logs (docs/backend.md 10)."""
    status, out = hw.status, loop.last_output
    frame = b"" if out is None else bytes(c for led in out.hardware.leds for c in led) + out.hardware.matrix
    return Facts(frame_no=loop.ticks, bytes_tx=status.bytes_tx, link_fps=status.fps,
                 render_fps=loop.fps, rtt_ms=status.rtt_ms, led_count=status.led_count, mode=state.mode,
                 preset=state.preset, connections=len(hub.connections), waiting=len(state.queue.waiting),
                 frame=frame)


class SceneSync:
    """State listener: the render loop shows what the state says (docs/backend.md 6, 7.4)."""

    MUSIC_EFFECT: type[Effect] = Rainbow  # until the music effect exists (plan step 8)

    def __init__(self, loop: RenderLoop) -> None:
        self._loop = loop
        self._shown = ("idle", Idle.id)  # (mode, effect id) the loop was given; it starts with idle

    def __call__(self, state: State) -> None:
        if state.mode == "manual":
            effect, params = PRESETS[state.preset], state.params
            drawing = state.drawing if state.matrix_mode == "drawing" else None
        elif state.mode == "music":
            effect, params, drawing = self.MUSIC_EFFECT, self.MUSIC_EFFECT.defaults(), None
        else:
            effect, params, drawing = Idle, {}, None
        key = (state.mode, effect.id)
        if key != self._shown:
            self._loop.set_effect(effect(), params)  # a new effect starts at t = 0
            self._shown = key
        elif dict(self._loop.scene.params) != params:
            self._loop.set_params(params)
        if self._loop.scene.drawing != drawing:
            self._loop.set_drawing(drawing)


def settings_or_exit() -> Settings:
    """The settings from the environment, including the checks only the HCL can
    do; a problem prints every bad variable and exits with 1."""
    try:
        settings = Settings.from_env()
        problems = hardware.check_settings(settings)
        if problems:
            raise SettingsError(problems)
        return settings
    except SettingsError as e:
        print(f"dod: {e}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None


def setup_logging(level: str) -> None:
    """The backend's and the HCL's real log (`docker logs`), next to uvicorn's."""
    for name, fmt in LOG_FORMATS.items():
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter(fmt))
            logger.addHandler(handler)
        logger.setLevel(level)
