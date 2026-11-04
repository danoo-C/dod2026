"""The connection to the HCL (docs/backend.md 5). The only module in `dod`
that imports `hcl`; everything else works with the backend's own types.

    link = open_link(settings)                 # or a link from hcl.testing.sim_link()
    hw = Hardware(link, bus, fallback_led_count=10, simulated=True)
    await hw.start()                           # events subscribed, then link.start()
    # the task supervisor runs hw.run_events() and hw.poll_status()
    hw.show(out.hardware)                      # every render tick; never raises, never waits
    await hw.stop()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import hcl

from dod.bus import (
    BoardConnected,
    BoardIncompatible,
    BoardLog,
    BoardLost,
    BoardText,
    Bus,
)
from dod.engine.output import HardwareFrame
from dod.settings import Settings

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0
MAX_REMEMBERED_ERRORS = 100  # distinct show() errors logged once each


def is_simulated(serial: str) -> bool:
    return serial == "sim" or serial.startswith("sim?")


def check_settings(settings: Settings) -> list[str]:
    """What settings.py can't check without hcl: the sim options and the LED
    count's upper limit. One line per problem, like SettingsError's."""
    problems = []
    try:
        hcl.open_link(settings.serial, baud=settings.baud)  # opens nothing, only parses
    except ValueError as e:
        problems.append(f"DOD_SERIAL={settings.serial!r}: {e}")
    if settings.led_count > hcl.MAX_LEDS:
        problems.append(f"DOD_LED_COUNT={settings.led_count}: at most {hcl.MAX_LEDS} LEDs fit into one frame")
    return problems


def open_link(settings: Settings) -> hcl.Link:
    """The link for the real backend; tests pass their own (hcl.testing)."""
    return hcl.open_link(settings.serial, baud=settings.baud)


@dataclass(frozen=True)
class HardwareStatus:
    """The backend's view of the link: what the pages and the logs need."""

    state: str  # "connecting", "connected", "disconnected", "incompatible"
    simulated: bool
    led_count: int  # the board's, or the fallback before it answered
    fps: float  # frames the board acknowledged per second
    rtt_ms: float | None
    error: str | None
    frames_sent: int = 0
    bytes_tx: int = 0

    def for_pages(self) -> dict[str, Any]:
        """The state's `hardware` part (docs/backend.md 6)."""
        return {"state": self.state, "simulated": self.simulated, "fps": self.fps, "error": self.error}

    def same_for_pages(self, other: HardwareStatus | None) -> bool:
        """Equal apart from the numbers that change all the time: the state is
        broadcast when this changes, not for every new fps value."""
        return other is not None and (self.state, self.simulated, self.error) == (
            other.state, other.simulated, other.error)


class Hardware:
    def __init__(self, link: hcl.Link, bus: Bus, *, fallback_led_count: int, simulated: bool,
                 on_status: Callable[[HardwareStatus], None] | None = None,
                 poll_seconds: float = POLL_SECONDS) -> None:
        self._link = link
        self._bus = bus
        self._fallback = fallback_led_count
        self._simulated = simulated
        self._on_status = on_status
        self._poll_seconds = poll_seconds
        self._device: hcl.DeviceInfo | None = None
        self._events: hcl.EventStream | None = None
        self._errors_seen: set[str] = set()
        self._status = self._read_status()

    # --- lifecycle

    async def start(self) -> None:
        """Listen to the link's events, then start it: connecting runs in the
        background, nothing waits for the board."""
        self._events = self._link.events()  # before start(), so the first Connected isn't missed
        await self._link.start()

    async def stop(self) -> None:
        await self._link.stop()

    # --- every render tick

    @property
    def led_count(self) -> int:
        """The connected board's LED count, or the fallback before any board answered."""
        return self._device.led_count if self._device is not None else self._fallback

    def show(self, frame: HardwareFrame) -> None:
        """One finished picture to the board. Never raises: a bad frame (always a
        bug, or a board with another LED count for one tick) is logged once per
        distinct message and skipped."""
        try:
            strip = bytes(c for led in frame.leds for c in led)
            self._link.submit(hcl.Frame(strip=strip, matrix=frame.matrix, brightness=frame.matrix_brightness))
        except (ValueError, TypeError, RuntimeError) as e:
            message = f"{type(e).__name__}: {e}"
            if message not in self._errors_seen and len(self._errors_seen) < MAX_REMEMBERED_ERRORS:
                self._errors_seen.add(message)
                log.error("frame not sent: %s", message)

    # --- status

    @property
    def status(self) -> HardwareStatus:
        """As of the last poll (or the last event)."""
        return self._status

    def link_status(self) -> dict[str, Any]:
        """Everything the HCL knows, fresh, for /api/status."""
        return self._link.status.to_dict()

    async def poll_status(self) -> None:
        """Task: read link.status once a second (docs/backend.md 5.6)."""
        while True:
            self._update_status()
            await asyncio.sleep(self._poll_seconds)

    def _read_status(self) -> HardwareStatus:
        s = self._link.status
        device = s.device
        if device is not None:
            self._device = device
        return HardwareStatus(
            state=s.state.value,
            simulated=device.simulated if device is not None else self._simulated,
            led_count=self.led_count,
            fps=s.fps,
            rtt_ms=s.rtt_ms,
            error=s.last_error if s.state is not hcl.LinkState.CONNECTED else None,
            frames_sent=s.frames_sent,
            bytes_tx=s.bytes_tx,
        )

    def _update_status(self) -> None:
        old, self._status = self._status, self._read_status()
        if not self._status.same_for_pages(old) and self._on_status is not None:
            self._on_status(self._status)

    # --- events

    async def run_events(self) -> None:
        """Task: the HCL's events become the backend's (docs/backend.md 5.5).
        Ends when the link stops."""
        if self._events is None:
            raise RuntimeError("start() first")
        async for event in self._events:
            self.handle_event(event)

    def handle_event(self, event: hcl.LinkEvent) -> None:
        """One HCL event: to the bus, to the real log, into the status."""
        match event:
            case hcl.Connected(device=device, rebooted=rebooted):
                self._device = device
                log.info("board connected: firmware %s, %d LEDs, %s%s%s", device.firmware_str, device.led_count,
                         device.color_order, ", simulated" if device.simulated else "",
                         ", it rebooted" if rebooted else "")
                self._bus.publish(BoardConnected(led_count=device.led_count, firmware=device.firmware_str,
                                                 simulated=device.simulated, rebooted=rebooted, at=event.at))
            case hcl.Disconnected(reason=reason):
                log.warning("board lost: %s", reason)
                self._bus.publish(BoardLost(reason=reason, at=event.at))
            case hcl.DeviceLog(level=level, text=text):
                if level >= hcl.LogLevel.WARN:
                    log.warning("board says (%s): %s", level.name, text)
                self._bus.publish(BoardLog(level=level.name, text=text, at=event.at))
            case hcl.RawText(line=line):
                log.info("board prints: %s", line)
                self._bus.publish(BoardText(line=line, at=event.at))
            case hcl.Incompatible(reason=reason, protocol=protocol):
                log.error("board is incompatible: %s (run ./dod esp upload)", reason)
                self._bus.publish(BoardIncompatible(reason=reason, protocol=protocol, at=event.at))
            case _:
                log.warning("unknown HCL event %r", event)
        self._update_status()
