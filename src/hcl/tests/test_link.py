"""The link against the simulated board (docs/hcl.md 4 and 11).

Timeouts are shortened so the tests stay fast. They wait for conditions with
a deadline instead of sleeping a fixed time, so a busy machine only makes
them slower, not red.
"""

import asyncio
import threading
import time

import pytest

from hcl import (
    Connected,
    DeviceInfo,
    DeviceLog,
    Disconnected,
    Frame,
    Incompatible,
    LinkState,
    LogLevel,
    RawText,
)
from hcl import protocol as p
from hcl.color import reorder
from hcl.link import Link, LinkOptions
from hcl.transport import Transport, TransportError
from hcl.transport.sim import SimTransport
from support import FAST, next_of, run, until

STRIP = bytes(range(30))
MATRIX = bytes([0x3C, 0x42, 0x81, 0x81, 0x81, 0x81, 0x42, 0x3C])


def frame(n=0, leds=10):
    """Frames that differ: the first LED's red value is n."""
    strip = bytes([n % 256]) + STRIP[1 : 3 * leds] if leds == 10 else bytes(3 * leds)
    return Frame(strip=strip, matrix=MATRIX, brightness=5)


class Rig:
    """A link to a simulated board, started and stopped around a test."""

    def __init__(self, url="sim", transport=None, **options):
        self.transport = transport or SimTransport.from_url(url)
        self.link = Link(self.transport, url=url, options=LinkOptions(**(FAST | options)))
        self.stream = self.link.events()  # listening from before the start

    @property
    def board(self):
        return self.transport.board

    @property
    def status(self):
        return self.link.status

    async def __aenter__(self):
        await self.link.start()
        return self

    async def __aexit__(self, *exc):
        await self.link.stop()

    async def connected(self):
        await until(lambda: self.status.state is LinkState.CONNECTED, what="CONNECTED")


# --- connecting -----------------------------------------------------------


@run
async def test_connects_and_reports_the_board():
    async with Rig() as rig:
        event = await next_of(rig.stream, Connected)
        assert event.device == DeviceInfo(protocol=p.PROTOCOL_VERSION, firmware=(0, 0, 0), led_count=10,
                                          color_order="GRB", simulated=True)
        assert event.rebooted is False
        s = rig.status
        assert s.state is LinkState.CONNECTED and s.device == event.device
        assert s.connected_since is not None and abs(s.connected_since - time.time()) < 5
        assert s.url == "sim"


@run
async def test_boot_text_comes_as_raw_text():
    async with Rig() as rig:
        lines = []
        async def collect():
            async for event in rig.stream:
                if isinstance(event, RawText):
                    lines.append(event.line)
                    if "entry 0x400805b4" in event.line:
                        return
        await asyncio.wait_for(collect(), 3)
        assert "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)" in lines


# --- sending ----------------------------------------------------------------


@run
async def test_frame_reaches_the_board():
    async with Rig() as rig:
        await rig.connected()
        rig.link.submit(frame(200))
        await until(lambda: rig.board.strip_rgb() == frame(200).strip, what="the frame on the board")
        assert rig.board.picture.matrix == MATRIX and rig.board.picture.brightness == 5
        await until(lambda: rig.status.frames_acked >= 1, what="an ACK")
        s = rig.status
        assert s.frames_sent >= 1 and s.rtt_ms is not None and s.rtt_ms > 0
        assert s.bytes_tx > 0 and s.bytes_rx > 0 and s.fps > 0


@run
async def test_colour_order_on_the_wire():
    async with Rig("sim?color_order=BRG") as rig:
        await rig.connected()
        rig.link.submit(frame(7))
        await until(lambda: rig.board.picture is not None, what="the frame on the board")
        # the board received BRG bytes; converted back they are the RGB that was submitted
        assert rig.board.picture.strip == reorder(frame(7).strip, "RGB", "BRG")
        assert rig.board.strip_rgb() == frame(7).strip


@run
async def test_frame_submitted_before_the_board_answers():
    rig = Rig("sim?boot_ms=150")
    rig.link.submit(frame(9))  # before start, even
    async with rig:
        await until(lambda: rig.board.strip_rgb() == frame(9).strip, what="the early frame on the board")


@run
async def test_newest_frame_wins():
    async with Rig("sim?latency_ms=60", ack_timeout_ms=200) as rig:
        await rig.connected()
        for n in range(100):
            rig.link.submit(frame(n))
        await until(lambda: rig.board.strip_rgb() == frame(99).strip, what="the newest frame")
        s = rig.status
        # at most the first and the last went out; everything in between was replaced
        assert s.frames_sent <= 3
        assert s.frames_replaced >= 97
        assert rig.board.frames_received == s.frames_sent


@run
async def test_one_frame_in_flight_at_a_time():
    # no rate cap to speak of, so only waiting for each ACK keeps the count down
    async with Rig("sim?latency_ms=30", ack_timeout_ms=200, max_fps=1000) as rig:
        await rig.connected()
        start = time.monotonic()
        while time.monotonic() - start < 0.3:
            rig.link.submit(frame(1))
            await asyncio.sleep(0.002)
        # each frame waits for the previous ACK (~30 ms), so ~10 in 0.3 s, never more
        assert rig.status.frames_sent <= 12
        assert rig.status.ack_timeouts == 0


@run
async def test_rate_cap():
    async with Rig("sim?latency_ms=1", max_fps=20) as rig:
        await rig.connected()
        start = time.monotonic()
        while time.monotonic() - start < 0.5:
            rig.link.submit(frame(2))
            await asyncio.sleep(0.001)
        assert rig.status.frames_sent <= 12  # 20 per second, plus a little slack


@run
async def test_keepalive_repeats_the_last_frame():
    async with Rig("sim?idle_after_ms=250") as rig:
        await rig.connected()
        rig.link.submit(frame(3))
        await until(lambda: rig.board.frames_received >= 1, what="the first frame")
        first_seen = time.monotonic()
        while time.monotonic() - first_seen < 0.6:
            assert not rig.board.idle, "the board went idle although the link is fine"
            await asyncio.sleep(0.02)
        assert rig.board.frames_received >= 4  # keepalive every 100 ms
        assert rig.board.strip_rgb() == frame(3).strip


@run
async def test_wrong_led_count():
    async with Rig() as rig:
        await rig.connected()
        with pytest.raises(ValueError, match="7 LEDs, the connected board has 10"):
            rig.link.submit(frame(leds=7))
        with pytest.raises(TypeError):
            rig.link.submit(b"not a frame")


@run
async def test_wrong_led_count_submitted_before_connecting_is_dropped():
    rig = Rig()
    rig.link.submit(frame(leds=7))  # nobody knows the LED count yet
    async with rig:
        await until(lambda: "7 LEDs" in (rig.status.last_error or ""), what="the error")
        assert rig.status.frames_sent == 0
        rig.link.submit(frame(4))  # a correct one still works afterwards
        await until(lambda: rig.board.strip_rgb() == frame(4).strip, what="the correct frame")


# --- losing the board -------------------------------------------------------


@run
async def test_board_reboot():
    # keepalive is slow here, so only the resend after the reboot can bring the picture back in time
    async with Rig("sim?reboot_every=0.3", keepalive_ms=5000) as rig:
        await next_of(rig.stream, Connected)
        rig.link.submit(frame(5))
        await until(lambda: rig.board.picture is not None, what="the frame")
        event = await next_of(rig.stream, Connected)
        assert event.rebooted is True
        # the reboot cleared the board; the link sent the last frame again
        await until(lambda: rig.board.boots >= 2 and rig.board.strip_rgb() == frame(5).strip,
                    timeout=0.5, what="the frame again right after the reboot")
        assert rig.status.state is LinkState.CONNECTED


@run
async def test_reconnects_after_an_unplug():
    async with Rig("sim?unplug_every=0.3&unplug_for=0.2") as rig:
        await next_of(rig.stream, Connected)
        rig.link.submit(frame(6))
        lost = await next_of(rig.stream, Disconnected)
        assert "unplugged" in lost.reason
        again = await next_of(rig.stream, Connected)
        assert again.rebooted is False  # a new connection, not a reboot seen while connected
        await until(lambda: rig.board.strip_rgb() == frame(6).strip, what="the frame after replugging")
        assert rig.status.reconnects >= 1


@run
async def test_ack_timeouts_end_the_connection():
    async with Rig("sim?drop=1") as rig:
        await rig.connected()
        rig.link.submit(frame(1))
        lost = await next_of(rig.stream, Disconnected)
        assert "3 ACK timeouts in a row" in lost.reason
        s = rig.status
        assert s.ack_timeouts >= 3 and s.frames_acked == 0
        await next_of(rig.stream, Connected)  # and it tries again
        assert rig.status.reconnects >= 1


@run
async def test_incompatible_board():
    async with Rig("sim?protocol=2") as rig:
        event = await next_of(rig.stream, Incompatible)
        assert event.protocol == 2 and "./dod esp upload" in event.reason
        rig.link.submit(frame(1))
        pings = rig.board.pings
        await until(lambda: rig.board.pings >= pings + 2, what="PINGs to the incompatible board")
        s = rig.status
        assert s.state is LinkState.INCOMPATIBLE and s.device is None
        assert rig.board.frames_received == 0  # nothing is sent to it


class SilentTransport(Transport):
    """Opens, but nothing ever answers."""

    def __init__(self):
        self.opens = 0

    def open(self):
        self.opens += 1

    def read(self, max_bytes, timeout):
        time.sleep(timeout)
        return b""

    def write(self, data):
        pass

    def close(self):
        pass


@run
async def test_no_hello():
    t = SilentTransport()
    async with Rig(transport=t) as rig:
        await until(lambda: "no HELLO" in (rig.status.last_error or ""), what="the HELLO timeout")
        await until(lambda: t.opens >= 2, what="a second attempt")
        assert rig.status.state is not LinkState.CONNECTED
        assert rig.status.reconnects >= 1


class BrokenTransport(SilentTransport):
    """Can't be opened at all."""

    def open(self):
        self.opens += 1
        raise TransportError("no such port: /dev/ttyUSB9")


@run
async def test_port_that_cant_be_opened():
    t = BrokenTransport()
    async with Rig(transport=t) as rig:
        await until(lambda: t.opens >= 3, what="repeated attempts")
        assert "can't open the port: no such port" in rig.status.last_error
        assert rig.status.state is LinkState.DISCONNECTED


@run
async def test_garbage_on_the_line():
    async with Rig("sim?garbage=0.5&seed=4") as rig:
        await rig.connected()
        for n in range(20):
            rig.link.submit(frame(n))
            await asyncio.sleep(0.01)
        await until(lambda: rig.status.frames_acked >= 15, what="ACKs through the noise")
        assert rig.status.garbage_bytes > 0
        assert rig.status.state is LinkState.CONNECTED


# --- events -----------------------------------------------------------------


@run
async def test_board_log_becomes_an_event():
    async with Rig() as rig:
        await rig.connected()
        with rig.transport._cond:  # what main.py does when something goes wrong
            rig.board._log(p.LOG_WARN, "matrix did not answer")
        event = await next_of(rig.stream, DeviceLog)
        assert event == DeviceLog(LogLevel.WARN, "matrix did not answer", at=event.at)


@run
async def test_slow_listener_doesnt_hold_up_the_others():
    async with Rig() as rig:
        slow = rig.link.events(queue_size=5)  # never read until the end
        await rig.connected()
        with rig.transport._cond:
            for n in range(50):
                rig.board._log(p.LOG_INFO, f"message {n}")
        texts = []
        while len(texts) < 50:
            event = await next_of(rig.stream, DeviceLog)
            texts.append(event.text)
        assert texts == [f"message {n}" for n in range(50)]  # the fast one: in order, after the earlier ones
        # the slow one kept only the newest 5, and knows how many it missed
        kept = [slow._queue.get_nowait() for _ in range(slow._queue.qsize())]
        assert [e.text for e in kept if isinstance(e, DeviceLog)][-1] == "message 49"
        assert len(kept) == 5 and slow.dropped > 0


@run
async def test_several_listeners_get_every_event():
    async with Rig() as rig:
        a, b = rig.link.events(), rig.link.events()
        ea = await next_of(a, Connected)
        eb = await next_of(b, Connected)
        assert ea is eb


# --- stopping ---------------------------------------------------------------


@run
async def test_stop():
    rig = Rig()
    async with rig:
        await rig.connected()
        rig.link.submit(frame(1))
    start = time.monotonic()
    await rig.link.stop()  # a second stop is fine
    assert time.monotonic() - start < 0.1
    assert not [t for t in threading.enumerate() if t.name == "hcl-io"]
    async for _ in rig.stream:  # the stream ends instead of waiting forever
        pass
    async for _ in rig.link.events():  # a listener added after stopping ends at once
        pass
    with pytest.raises(RuntimeError, match="stopped"):
        rig.link.submit(frame(1))


@run
async def test_stop_is_quick_even_while_reconnecting():
    async with Rig(transport=BrokenTransport(), backoff_ms=(5000,)) as rig:
        await asyncio.sleep(0.05)  # now waiting 5 s before the next attempt
        start = time.monotonic()
        await rig.link.stop()
        assert time.monotonic() - start < 1.0


@run
async def test_cant_start_twice():
    async with Rig() as rig:
        with pytest.raises(RuntimeError, match="already started"):
            await rig.link.start()


def test_bad_options():
    with pytest.raises(ValueError):
        LinkOptions(ack_timeout_ms=0)
    with pytest.raises(ValueError):
        LinkOptions(backoff_ms=())
