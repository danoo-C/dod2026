"""The render loop (docs/backend.md 7.1) and the task supervisor (4.2),
without any hardware."""

import asyncio
import time

import pytest

from dod.engine.effects.base import Context, Effect, Param
from dod.engine.effects.idle import Idle
from dod.engine.effects.rainbow import Rainbow
from dod.engine.effects.solid import Solid
from dod.engine.loop import RenderLoop
from dod.engine.output import OutputStage
from dod.engine.picture import Picture
from dod.tasks import Supervisor
from support import run, until


class FakeDisplay:
    def __init__(self, led_count=10):
        self.led_count = led_count
        self.frames = []
        self.times = []

    def show(self, frame):
        self.frames.append(frame)
        self.times.append(time.monotonic())


class Broken(Effect):
    id = "broken"
    name = "Pokazený"

    def render(self, ctx):
        raise ZeroDivisionError("oops")


class WrongCount(Effect):
    id = "wrong"
    name = "Zlý počet"

    def render(self, ctx):
        return Picture.black(ctx.led_count + 1)


class Clock(Effect):
    """Shows its time: red = t / 100, green = the speed parameter."""
    id = "clock"
    name = "Hodiny"
    params = (Param.slider("speed", "Rýchlosť", 0, 1, default=0.5),)

    def render(self, ctx):
        return Picture(leds=[(ctx.t / 100, ctx.params["speed"], 0)] * ctx.led_count)


def make(effect=None, **kwargs):
    display = FakeDisplay(kwargs.pop("led_count", 10))
    stage = OutputStage(brightness=1.0, power_limit_ma=100_000)
    now = [0.0]
    loop = RenderLoop(display, stage, effect=effect, clock=lambda: now[0], **kwargs)
    return loop, display, now


def red(display, i=-1):
    return display.frames[i].leds[0][0]


# --- one tick at a time -------------------------------------------------------


def test_a_tick_renders_and_shows():
    loop, display, _ = make(Rainbow())
    loop.tick(0.0)
    assert len(display.frames) == 1 and display.frames[0].led_count == 10
    assert loop.last_output.hardware == display.frames[0]


def test_it_renders_for_the_displays_led_count():
    loop, display, _ = make(Rainbow())
    display.led_count = 12  # a board with 12 LEDs answered
    loop.tick(0.0)
    assert display.frames[0].led_count == 12


def test_every_third_tick_goes_to_the_preview():
    previews = []
    loop, _, _ = make(Rainbow(), on_preview=previews.append)
    for i in range(9):
        loop.tick(i / 30)
    assert len(previews) == 3


def test_the_effects_time_and_parameters():
    loop, display, now = make(Clock())
    now[0] = 10.0
    loop.set_effect(Clock(), {"speed": 1.0})  # starts at t = 0
    loop.tick(10.0)
    loop.tick(60.0)
    assert red(display, 0) == 0 and red(display, 1) == round((50 / 100) ** 2.2 * 255)
    loop.set_params({"speed": 0.0})  # keeps the time going
    loop.tick(70.0)
    assert red(display) == round((60 / 100) ** 2.2 * 255) and display.frames[-1].leds[0][1] == 0


def test_a_drawing_replaces_the_effects_8x8():
    drawing = bytes.fromhex("ff818181818181ff")
    loop, display, _ = make(Rainbow())
    loop.set_drawing(drawing)
    loop.tick(0.0)
    assert display.frames[-1].matrix == drawing and display.frames[-1].matrix_brightness > 0
    loop.set_effect(Solid())  # the drawing stays when the effect changes
    loop.tick(1 / 30)
    assert display.frames[-1].matrix == drawing
    loop.set_drawing(None)
    loop.tick(2 / 30)
    assert display.frames[-1].matrix != drawing
    with pytest.raises(ValueError):
        loop.set_drawing(bytes(7))


def test_without_params_an_effect_gets_its_defaults():
    loop, _, _ = make(Solid())
    assert loop.scene.params == Solid.defaults()


def test_a_broken_effect_shows_black_then_idle(caplog):
    fallbacks = []
    loop, display, _ = make(Broken(), on_fallback=fallbacks.append)
    for i in range(9):
        loop.tick(i / 30)
    assert all(f.leds == ((0, 0, 0),) * 10 for f in display.frames)
    assert isinstance(loop.scene.effect, Broken) and not fallbacks
    loop.tick(9 / 30)  # the 10th failure in a row
    assert isinstance(loop.scene.effect, Idle) and fallbacks == ["broken"]
    loop.tick(10 / 30)
    assert display.frames[-1].leds != ((0, 0, 0),) * 10  # idle shows something
    assert sum("effect failed" in r.getMessage() for r in caplog.records) == 1  # logged once, not 10 times


def test_failures_must_be_in_a_row():
    loop, _, _ = make(Broken())
    for i in range(9):
        loop.tick(i / 30)
    loop.set_effect(Broken())  # a new start resets the count
    for i in range(9):
        loop.tick(1 + i / 30)
    assert isinstance(loop.scene.effect, Broken)


def test_a_picture_with_the_wrong_led_count_is_a_failure():
    loop, display, _ = make(WrongCount())
    loop.tick(0)
    assert display.frames[0].leds == ((0, 0, 0),) * 10


# --- running in real time -----------------------------------------------------


@run
async def test_it_keeps_30_fps():
    display = FakeDisplay()
    loop = RenderLoop(display, OutputStage(brightness=1, power_limit_ma=10_000), effect=Rainbow())
    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.5)  # settle
    start = loop.ticks
    await asyncio.sleep(3.0)
    task.cancel()
    assert 87 <= loop.ticks - start <= 93  # 30 fps +-1 over 3 s
    assert 29 <= loop.fps <= 31


@run
async def test_a_late_tick_doesnt_cause_a_burst():
    class Stall(Effect):
        id = "stall"
        name = "Zaseknutie"
        done = False

        def render(self, ctx):
            if ctx.t > 0.3 and not Stall.done:
                Stall.done = True
                time.sleep(0.25)  # blocks the event loop like a bug would: ~7 slots missed
            return Picture.black(ctx.led_count)

    display = FakeDisplay()
    loop = RenderLoop(display, OutputStage(brightness=1, power_limit_ma=10_000), effect=Stall())
    task = asyncio.create_task(loop.run())
    await until(lambda: Stall.done, what="the stall")
    await asyncio.sleep(0.5)
    task.cancel()
    gaps = [b - a for a, b in zip(display.times, display.times[1:])]
    stall = max(range(len(gaps)), key=gaps.__getitem__)
    after = gaps[stall + 1:stall + 6]
    assert gaps[stall] > 0.2
    assert all(g > 0.005 for g in after[1:]), after  # no rapid catch-up ticks
    assert sum(after) > 4 * (1 / 30) * 0.8


# --- the supervisor -----------------------------------------------------------


@run
async def test_a_crashed_task_is_restarted():
    runs = []

    async def flaky():
        runs.append(1)
        if len(runs) < 3:
            raise RuntimeError("boom")
        await asyncio.sleep(10)

    tasks = Supervisor(restart_seconds=0.01)
    tasks.start("flaky", flaky)
    await until(lambda: len(runs) == 3, what="two restarts")
    assert tasks.restarts["flaky"] == 2 and tasks.running == ["flaky"]
    await tasks.stop()
    assert tasks.running == []


@run
async def test_a_task_that_ends_is_restarted_too():
    runs = []

    async def short():
        runs.append(1)

    tasks = Supervisor(restart_seconds=0.01)
    tasks.start("short", short)
    await until(lambda: len(runs) >= 3, what="restarts")
    await tasks.stop()


@run
async def test_one_crashing_task_doesnt_stop_the_others():
    ticks = []

    async def steady():
        while True:
            ticks.append(1)
            await asyncio.sleep(0.01)

    async def crashing():
        raise RuntimeError("boom")

    tasks = Supervisor(restart_seconds=0.01)
    tasks.start("steady", steady)
    tasks.start("crashing", crashing)
    await asyncio.sleep(0.2)
    assert len(ticks) > 10 and tasks.restarts["crashing"] > 3 and tasks.restarts["steady"] == 0
    with pytest.raises(ValueError):
        tasks.start("steady", steady)
    await tasks.stop()
