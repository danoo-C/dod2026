"""The whole app with its lifespan, against the simulated board (docs/backend.md 4.1)."""

import asyncio
import logging
import time

from fastapi.testclient import TestClient
from hcl.testing import sim_link

from dod.bus import BoardConnected, BoardLost
from dod.engine.color import parse_hex
from dod.engine.effects.base import Effect
from dod.engine.effects.idle import Idle
from dod.engine.output import OutputStage
from dod.engine.picture import Picture
from dod.main import create_app
from dod.settings import Settings
from support import run, until

SETTINGS = Settings(internal_key="test-key", public_url="http://192.168.137.1:8000")


class Broken(Effect):
    id = "broken"
    name = "Pokazený"

    def render(self, ctx):
        raise RuntimeError("oops")


async def next_of(sub, kind, timeout=3.0):
    async def find():
        async for event in sub:
            if isinstance(event, kind):
                return event
    return await asyncio.wait_for(find(), timeout)


@run
async def test_it_starts_idle_and_the_board_shows_it():
    link, board = sim_link()
    app = create_app(SETTINGS, link=link)
    async with app.router.lifespan_context(app):
        await until(lambda: board.strip_rgb() is not None, what="the first frame")
        first = board.strip_rgb()
        await until(lambda: board.strip_rgb() != first, what="the picture moving")
        assert len(board.strip_rgb()) == 30
        assert app.state.state.mode == "idle" and app.state.loop.scene.effect.id == "idle"


@run
async def test_the_board_follows_the_state():
    link, board = sim_link()
    app = create_app(SETTINGS, link=link)
    async with app.router.lifespan_context(app):
        state, loop = app.state.state, app.state.loop
        state.connected("aaaa11112222")
        state.join("aaaa11112222")
        state.set_preset("solid", by="aaaa11112222")
        assert loop.scene.effect.id == "solid"
        # solid's default colour, through brightness 0.8 and gamma
        stage = OutputStage(brightness=SETTINGS.brightness, power_limit_ma=SETTINGS.power_limit_ma)
        expected = stage.apply(Picture([parse_hex("#ff2a6d")] * 10), now=0).hardware
        await until(lambda: board.strip_rgb() == bytes(c for led in expected.leds for c in led),
                    what="the solid colour on the board")
        state.set_param("color", "#00ff00", by="aaaa11112222")
        assert loop.scene.params["color"] == "#00ff00" and loop.scene.effect.id == "solid"
        state.set_matrix("drawing", "ff818181818181ff", by="aaaa11112222")
        await until(lambda: board.picture.matrix == bytes.fromhex("ff818181818181ff"), what="the drawing")


@run
async def test_the_queue_clock_ends_turns():
    link, board = sim_link()
    app = create_app(Settings(turn_seconds=0.5, internal_key="k"), link=link)
    async with app.router.lifespan_context(app):
        state = app.state.state
        for who in ("aaaa11112222", "bbbb33334444"):
            state.connected(who)
            state.join(who)
        assert state.queue.controller == "aaaa11112222"
        await until(lambda: state.queue.controller == "bbbb33334444", what="the next turn", timeout=2)


def test_status_over_http_and_30_fps():
    link, board = sim_link()
    with TestClient(create_app(SETTINGS, link=link)) as client:
        time.sleep(2.5)  # both the loop and the link measure their fps over the last 2 s
        status = client.get("/api/status").json()
        assert status["link"]["state"] == "connected"
        assert status["link"]["device"]["simulated"] is True
        assert 28 <= status["link"]["fps"] <= 31
        assert 29 <= status["render"]["fps"] <= 31
        assert status["render"]["effect"] == "idle" and status["render"]["led_count"] == 10
        assert status["render"]["mode"] == "idle"
        assert sorted(status["tasks"]["running"]) == ["hcl events", "queue clock", "render loop", "state broadcaster", "status poller"]


@run
async def test_unplugging_doesnt_stop_the_loop():
    link, board = sim_link()
    app = create_app(SETTINGS, link=link)
    async with app.router.lifespan_context(app):
        events = app.state.bus.subscribe()
        await until(lambda: board.strip_rgb() is not None, what="the first frame")
        board.unplug()
        await next_of(events, BoardLost)
        ticks = app.state.loop.ticks
        await asyncio.sleep(0.3)
        assert app.state.loop.ticks >= ticks + 6  # still rendering (and the previews with it)
        board.replug()
        await next_of(events, BoardConnected)
        received = board.frames_received
        await until(lambda: board.frames_received > received + 5, what="frames after replugging")


@run
async def test_a_board_with_12_leds_gets_12_led_frames():
    link, board = sim_link("sim?led_count=12")
    app = create_app(SETTINGS, link=link)
    async with app.router.lifespan_context(app):
        await until(lambda: board.strip_rgb() is not None and len(board.strip_rgb()) == 36, what="12-LED frames")
        assert app.state.hardware.led_count == 12


@run
async def test_a_broken_effect_doesnt_stop_the_loop():
    link, board = sim_link()
    app = create_app(SETTINGS, link=link)
    async with app.router.lifespan_context(app):
        loop = app.state.loop
        loop.set_effect(Broken())
        await until(lambda: isinstance(loop.scene.effect, Idle), what="the fallback to idle")
        ticks = loop.ticks
        await until(lambda: loop.ticks > ticks + 5, what="ticks after the fallback")


@run
async def test_the_internal_urls_are_logged(caplog):
    link, _ = sim_link()
    app = create_app(SETTINGS, link=link)
    with caplog.at_level(logging.INFO, logger="dod"):
        async with app.router.lifespan_context(app):
            pass
    messages = [r.getMessage() for r in caplog.records]
    assert "main screen:  http://192.168.137.1:8000/internal/main?key=test-key" in messages
    assert "logging page: http://192.168.137.1:8000/internal/logging?key=test-key" in messages


@run
async def test_shutdown_stops_everything():
    link, board = sim_link()
    app = create_app(SETTINGS, link=link)
    async with app.router.lifespan_context(app):
        await until(lambda: board.strip_rgb() is not None, what="the first frame")
        tasks = app.state.tasks
    assert tasks.running == []
    assert link.status.state.value == "disconnected"
