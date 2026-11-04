"""The HCL seam (docs/backend.md 5), against the simulated board."""

import asyncio
import logging

from hcl import DeviceLog, LogLevel
from hcl.testing import sim_link

from dod.bus import BoardConnected, BoardIncompatible, BoardLog, BoardLost, BoardText, Bus
from dod.engine.output import HardwareFrame
from dod.hardware import Hardware, HardwareStatus, check_settings
from dod.settings import Settings
from dod.tasks import Supervisor
from support import run, until

MATRIX = bytes([0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81])


def frame(n=10, red=200):
    return HardwareFrame(leds=((red, 1, 2),) + ((0, 0, 0),) * (n - 1), matrix=MATRIX, matrix_brightness=5)


def strip_bytes(f):
    return bytes(c for led in f.leds for c in led)


class Rig:
    """A Hardware on a simulated board, with its two tasks running."""

    def __init__(self, url="sim"):
        self.link, self.board = sim_link(url)
        self.bus = Bus()
        self.events = self.bus.subscribe()
        self.statuses = []
        self.hw = Hardware(self.link, self.bus, fallback_led_count=10, simulated=True,
                           on_status=self.statuses.append, poll_seconds=0.05)
        self.tasks = Supervisor(restart_seconds=0.01)

    async def __aenter__(self):
        await self.hw.start()
        self.tasks.start("hcl events", self.hw.run_events)
        self.tasks.start("status poller", self.hw.poll_status)
        return self

    async def __aexit__(self, *exc):
        await self.tasks.stop()
        await self.hw.stop()

    async def next(self, kind, timeout=3.0):
        async def find():
            async for event in self.events:
                if isinstance(event, kind):
                    return event
        return await asyncio.wait_for(find(), timeout)


@run
async def test_connects_and_tells_the_bus():
    async with Rig() as rig:
        event = await rig.next(BoardConnected)
        assert (event.led_count, event.firmware, event.simulated, event.rebooted) == (10, "0.0.0", True, False)
        assert rig.hw.status.state == "connected" and rig.hw.status.simulated and rig.hw.status.error is None
        assert rig.statuses and rig.statuses[-1].state == "connected"


@run
async def test_show_reaches_the_board():
    async with Rig() as rig:
        rig.hw.show(frame())
        await until(lambda: rig.board.strip_rgb() == strip_bytes(frame()), what="the frame on the board")
        assert rig.board.picture.matrix == MATRIX and rig.board.picture.brightness == 5


@run
async def test_the_led_count_follows_the_board():
    async with Rig("sim?led_count=12&boot_ms=300") as rig:
        assert rig.hw.led_count == 10  # nobody answered yet: the fallback
        await rig.next(BoardConnected)
        assert rig.hw.led_count == 12 and rig.hw.status.led_count == 12
        rig.hw.show(frame(12))
        await until(lambda: rig.board.strip_rgb() == strip_bytes(frame(12)), what="a 12-LED frame")


@run
async def test_show_never_raises_and_logs_each_problem_once(caplog):
    async with Rig("sim?led_count=12") as rig:
        await rig.next(BoardConnected)
        with caplog.at_level(logging.ERROR, logger="dod.hardware"):
            for _ in range(5):
                rig.hw.show(frame(10))  # the board has 12
        assert [r.getMessage() for r in caplog.records].count(
            "frame not sent: ValueError: frame has 10 LEDs, the connected board has 12") == 1
    rig.hw.show(frame(12))  # after stop: still no exception


@run
async def test_the_boards_log_messages_reach_the_bus_and_warnings_the_real_log(caplog):
    # the simulated board only logs about bad frames, and the link never lets one
    # through, so the HCL's own (public) event is fed in directly
    async with Rig() as rig:
        with caplog.at_level(logging.INFO, logger="dod.hardware"):
            rig.hw.handle_event(DeviceLog(level=LogLevel.INFO, text="matrix ok"))
            rig.hw.handle_event(DeviceLog(level=LogLevel.WARN, text="brownout"))
        first, second = await rig.next(BoardLog), await rig.next(BoardLog)
        assert (first.level, first.text, second.level, second.text) == ("INFO", "matrix ok", "WARN", "brownout")
        assert [r.getMessage() for r in caplog.records] == ["board says (WARN): brownout"]


@run
async def test_the_boot_text_reaches_the_bus():
    async with Rig() as rig:
        lines = []
        while not any("POWERON_RESET" in line for line in lines):
            lines.append((await rig.next(BoardText)).line)


@run
async def test_unplug_and_replug():
    async with Rig() as rig:
        await rig.next(BoardConnected)
        rig.board.unplug()
        lost = await rig.next(BoardLost)
        assert "unplugged" in lost.reason
        await until(lambda: rig.hw.status.state != "connected" and rig.hw.status.error, what="the status")
        rig.board.replug()
        again = await rig.next(BoardConnected)
        assert again.rebooted is False
        rig.hw.show(frame(red=9))
        await until(lambda: rig.board.strip_rgb() == strip_bytes(frame(red=9)), what="a frame after replugging")
        # the status was reported when it changed, not on every poll (every 50 ms)
        states = [s.state for s in rig.statuses]
        first = states.index("connected")
        assert "connected" in states[first + 1:] and set(states[first + 1:]) - {"connected"}, states
        assert len(states) < 10, states


@run
async def test_an_incompatible_board():
    async with Rig("sim?protocol=99") as rig:
        event = await rig.next(BoardIncompatible)
        assert event.protocol == 99
        await until(lambda: rig.hw.status.state == "incompatible", what="the status")


def test_the_status_for_the_pages():
    a = HardwareStatus(state="connected", simulated=False, led_count=10, fps=29.9, rtt_ms=5.0, error=None)
    assert a.for_pages() == {"state": "connected", "simulated": False, "fps": 29.9, "error": None}
    assert a.same_for_pages(HardwareStatus("connected", False, 10, 12.0, 9.0, None))  # only numbers changed
    assert not a.same_for_pages(HardwareStatus("disconnected", False, 10, 0, None, "port lost"))
    assert not a.same_for_pages(None)


def test_check_settings():
    assert check_settings(Settings()) == []
    assert check_settings(Settings(serial="/dev/ttyUSB0")) == []
    [problem] = check_settings(Settings(serial="sim?leds=12"))
    assert problem.startswith("DOD_SERIAL='sim?leds=12': unknown sim option 'leds'")
    [problem] = check_settings(Settings(led_count=500))
    assert problem == "DOD_LED_COUNT=500: at most 167 LEDs fit into one frame"
