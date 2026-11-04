"""hcl.testing: the helper the backend's tests use (docs/hcl.md 3.6)."""

import asyncio
import time

import pytest

import hcl
from hcl import Connected, Disconnected, Frame, LinkState
from hcl.testing import FAST, SimBoard, sim_link
from support import next_of, run, until

STRIP = bytes(range(30))
MATRIX = bytes([0x18, 0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x3C, 0x18])


def test_the_transports_stay_out_of_the_public_api():
    assert not {"SimTransport", "SerialTransport", "Transport", "SimBoard", "sim_link"} & set(dir(hcl))


def test_fast_timings_are_read_only():
    with pytest.raises(TypeError):
        FAST["ack_timeout_ms"] = 1  # type: ignore[index]
    assert FAST | {"max_fps": 1000} == {**FAST, "max_fps": 1000}


def test_timings_are_checked_like_open_link():
    with pytest.raises(ValueError, match="unknown link option"):
        sim_link(ack_timout_ms=10)
    with pytest.raises(ValueError, match="not a sim URL"):
        sim_link("/dev/ttyUSB0")
    with pytest.raises(ValueError, match="unknown sim option"):
        sim_link("sim?leds=12")


def test_board_options_come_from_the_url():
    link, board = sim_link("sim?led_count=12")
    assert isinstance(board, SimBoard)
    assert board.led_count == 12
    assert board.plugged and board.strip_rgb() is None and board.frames_received == 0


@run
async def test_the_board_shows_submitted_frames():
    link, board = sim_link()
    await link.start()
    try:
        link.submit(Frame(strip=STRIP, matrix=MATRIX, brightness=7))
        await until(lambda: board.strip_rgb() == STRIP, what="the frame on the board")
        assert board.picture.matrix == MATRIX and board.picture.brightness == 7
        assert board.frames_received >= 1 and board.boots == 1 and not board.idle
        assert link.status.device.simulated
    finally:
        await link.stop()


@run
async def test_unplug_and_replug():
    link, board = sim_link()
    events = link.events()
    await link.start()
    try:
        await next_of(events, Connected)
        link.submit(Frame(strip=STRIP, matrix=MATRIX, brightness=7))
        await until(lambda: board.strip_rgb() == STRIP, what="the frame on the board")

        board.unplug()
        assert not board.plugged
        lost = await next_of(events, Disconnected)
        assert "unplugged" in lost.reason

        # stays gone, however often the link tries (every 40 ms), until it is plugged back in
        await until(lambda: (link.status.last_error or "").startswith("can't open the port"),
                    what="a failed attempt to reopen")
        await asyncio.sleep(0.3)
        assert link.status.state is not LinkState.CONNECTED
        assert "unplugged" in link.status.last_error

        board.replug()
        started = time.monotonic()
        again = await next_of(events, Connected)
        assert again.rebooted is False
        assert time.monotonic() - started < 1  # the fast timings retry within 40 ms
        await until(lambda: board.strip_rgb() == STRIP, what="the frame again after replugging")
        assert board.boots == 2  # opening the port powered it on again
    finally:
        await link.stop()


@run
async def test_unplugged_before_start_connects_only_after_replug():
    link, board = sim_link()
    board.unplug()
    events = link.events()
    await link.start()
    try:
        await until(lambda: link.status.last_error is not None, what="a failed attempt")
        assert link.status.state is not LinkState.CONNECTED
        board.replug()
        await next_of(events, Connected)
    finally:
        await link.stop()
