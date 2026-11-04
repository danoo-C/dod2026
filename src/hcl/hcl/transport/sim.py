"""The simulated board (docs/hcl.md 6).

A transport whose other end is a fake ESP32 in memory instead of a USB
cable. It speaks the protocol with the board's own code (protocol.py), so the
whole link runs exactly as with real hardware.

    sim                                  a healthy board
    sim?latency_ms=8&drop=0.02&seed=1    a board with faults, for tests

Options (all optional):

    latency_ms     time until an answer arrives                  4
    boot_ms        time from power-on to the first output        20
    drop           share of FRAMEs that get lost (no ACK)        0
    garbage        share of answers with noise before them       0
    reboot_every   seconds between reboots, 0 = never            0
    unplug_every   seconds between unplugs, 0 = never            0
    unplug_for     seconds an unplug lasts                       1
    idle_after_ms  no FRAME for this long = idle animation       3000
    led_count      LEDs on the strip                             10
    color_order    the strip's colour order                      GRB
    protocol       protocol version in HELLO                     PROTOCOL_VERSION
    seed           seed for drop and garbage, for repeatable tests
"""

from __future__ import annotations

import heapq
import itertools
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from urllib.parse import parse_qsl

from hcl import protocol
from hcl.color import reorder
from hcl.transport.base import Transport, TransportError

FIRMWARE = (0, 0, 0)  # the link marks the board as simulated instead (DeviceInfo.simulated)

# What a real ESP32 prints when it resets (the ROM bootloader, at 115200 baud).
BOOT_TEXT = (
    b"ets Jul 29 2019 12:21:46\r\n"
    b"\r\n"
    b"rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)\r\n"
    b"configsip: 0, SPIWP:0xee\r\n"
    b"mode:DIO, clock div:2\r\n"
    b"entry 0x400805b4\r\n"
    b"simulated board, no hardware attached\r\n"
)
# What MicroPython prints when main.py exits to the REPL.
REPL_TEXT = (
    b"MicroPython v1.29.0 on 2026-09-30; Generic ESP32 module with ESP32 (simulated)\r\n"
    b'Type "help()" for more information.\r\n'
    b">>> "
)


@dataclass(frozen=True)
class SimOptions:
    latency_ms: float = 4.0
    boot_ms: float = 20.0
    drop: float = 0.0
    garbage: float = 0.0
    reboot_every: float = 0.0
    unplug_every: float = 0.0
    unplug_for: float = 1.0
    idle_after_ms: float = 3000.0
    led_count: int = 10
    color_order: str = "GRB"
    protocol: int = protocol.PROTOCOL_VERSION
    seed: int | None = None

    def __post_init__(self) -> None:
        for name in ("latency_ms", "boot_ms", "reboot_every", "unplug_every", "unplug_for", "idle_after_ms"):
            if getattr(self, name) < 0:
                raise ValueError(f"sim option {name} must not be negative")
        for name in ("drop", "garbage"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"sim option {name} must be between 0 and 1")
        if not 1 <= self.led_count <= (protocol.MAX_PAYLOAD - protocol.FRAME_FIXED) // 3:
            raise ValueError(f"sim option led_count out of range: {self.led_count}")
        if sorted(self.color_order) != ["B", "G", "R"]:
            raise ValueError(f"sim option color_order must be a mix of R, G and B, got {self.color_order!r}")
        if not 0 <= self.protocol <= 255:
            raise ValueError(f"sim option protocol out of range: {self.protocol}")


def parse_sim_url(url: str) -> SimOptions:
    """'sim' or 'sim?key=value&...' -> SimOptions. Unknown keys are an error."""
    base, _, query = url.partition("?")
    if base != "sim":
        raise ValueError(f"not a sim URL: {url!r}")
    types = {f.name: f.type for f in fields(SimOptions)}
    values: dict[str, object] = {}
    for key, raw in parse_qsl(query, keep_blank_values=True):
        if key not in types:
            raise ValueError(f"unknown sim option {key!r}, known: {', '.join(types)}")
        try:
            if key == "color_order":
                values[key] = raw.upper()
            elif key in ("led_count", "protocol", "seed"):
                values[key] = int(raw)
            else:
                values[key] = float(raw)
        except ValueError:
            raise ValueError(f"sim option {key} has a bad value: {raw!r}") from None
    return SimOptions(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Picture:
    """What the fake board shows: the strip in its own colour order, as received."""

    strip: bytes
    matrix: bytes
    brightness: int


class FakeBoard:
    """The ESP32 behind the simulated port. Behaves like main.py (docs/hcl.md 7.2)."""

    def __init__(self, options: SimOptions, rng: random.Random, clock: Callable[[], float],
                 send: Callable[[float, bytes], None]) -> None:
        self._o = options
        self._rng = rng
        self._clock = clock
        self._send_raw = send  # (delay in seconds, bytes) -> scheduled for reading
        self.boots = 0
        self._reset_state()

    def _reset_state(self) -> None:
        self._parser = protocol.Parser(keep_garbage=0)
        self.picture: Picture | None = None
        self.frames_received = 0
        self.frames_dropped = 0
        self.pings = 0
        self.in_repl = False
        self.ignored_while_booting = 0  # bytes that arrived before main.py was running
        self._last_frame_at: float | None = None
        self._ready_at = 0.0

    # --- what tests look at

    def strip_rgb(self) -> bytes | None:
        """The shown strip converted back to RGB, or None before the first frame."""
        if self.picture is None:
            return None
        return reorder(self.picture.strip, self._o.color_order, "RGB")

    @property
    def idle(self) -> bool:
        """True while the board would show its own idle animation."""
        if self._last_frame_at is None:
            return True
        return self._clock() - self._last_frame_at >= self._o.idle_after_ms / 1000

    @property
    def parser_garbage(self) -> int:
        return self._parser.garbage_count

    # --- driven by the transport

    def power_on(self) -> None:
        """Boot from scratch, like after a reset: boot text, then HELLO."""
        self.boots += 1
        self._reset_state()
        delay = self._o.boot_ms / 1000
        self._ready_at = self._clock() + delay
        self._send_raw(delay, BOOT_TEXT)
        self._send_raw(delay, protocol.encode(protocol.HELLO, self._hello()))

    def receive(self, data: bytes) -> None:
        if self._clock() < self._ready_at:
            # still booting: like a real ESP32, nothing is listening yet and the bytes are lost
            self.ignored_while_booting += len(data)
            return
        if self.in_repl:
            return  # the REPL doesn't speak the protocol
        for type_, payload in self._parser.feed(data):
            self._handle(type_, payload)

    def _handle(self, type_: int, payload: bytes) -> None:
        if type_ == protocol.FRAME:
            try:
                seq, strip, matrix, brightness = protocol.parse_frame(payload)
            except ValueError as e:
                self._log(protocol.LOG_ERROR, f"bad frame: {e}")
                return
            if len(strip) != 3 * self._o.led_count:
                self._log(protocol.LOG_ERROR, f"frame has {len(strip) // 3} LEDs, this board has {self._o.led_count}")
                return
            if self._o.drop and self._rng.random() < self._o.drop:
                self.frames_dropped += 1
                return
            self.picture = Picture(strip=bytes(strip), matrix=bytes(matrix), brightness=brightness)
            self.frames_received += 1
            self._last_frame_at = self._clock()
            self._send(protocol.ACK, protocol.ack_payload(seq))
        elif type_ == protocol.PING:
            self.pings += 1
            self._send(protocol.HELLO, self._hello())
        elif type_ == protocol.REPL:
            self._log(protocol.LOG_INFO, "entering repl")
            self.in_repl = True
            self._send_raw(self._o.latency_ms / 1000, REPL_TEXT)
        else:
            self._log(protocol.LOG_WARN, f"unknown message type 0x{type_:02x}")

    def _hello(self) -> bytes:
        payload = protocol.hello_payload(FIRMWARE, self._o.led_count, self._o.color_order)
        if self._o.protocol != protocol.PROTOCOL_VERSION:
            payload = bytes([self._o.protocol]) + payload[1:]
        return payload

    def _log(self, level: int, text: str) -> None:
        self._send(protocol.LOG, protocol.log_payload(level, text))

    def _send(self, type_: int, payload: bytes) -> None:
        data = protocol.encode(type_, payload)
        if self._o.garbage and self._rng.random() < self._o.garbage:
            noise = bytes(self._rng.randrange(256) for _ in range(self._rng.randrange(1, 9)))
            data = noise + data
        self._send_raw(self._o.latency_ms / 1000, data)


class SimTransport(Transport):
    """A transport to the fake board. Opening it powers the board on."""

    simulated = True

    def __init__(self, options: SimOptions | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.options = options or SimOptions()
        self._clock = clock
        self._rng = random.Random(self.options.seed)
        self._cond = threading.Condition()
        self._out: list[tuple[float, int, bytes]] = []  # (due time, order, bytes), a heap
        self._order = itertools.count()
        self._open = False
        self._lost = False  # unplugged while open
        self._unplugged_until = 0.0
        self._next_reboot: float | None = None
        self._next_unplug: float | None = None
        self.board = FakeBoard(self.options, self._rng, clock, self._schedule)

    @classmethod
    def from_url(cls, url: str) -> SimTransport:
        return cls(parse_sim_url(url))

    # --- Transport

    def open(self) -> None:
        with self._cond:
            now = self._clock()
            if now < self._unplugged_until:
                raise TransportError("simulated board is unplugged")
            self._out.clear()
            self._open = True
            self._lost = False
            o = self.options
            self._next_reboot = now + o.reboot_every if o.reboot_every else None
            self._next_unplug = now + o.unplug_every if o.unplug_every else None
            self.board.power_on()
            self._cond.notify_all()

    def read(self, max_bytes: int, timeout: float) -> bytes:
        with self._cond:
            deadline = self._clock() + timeout
            while True:
                now = self._clock()
                self._tick(now)
                self._check_usable()
                data = self._take_due(now, max_bytes)
                if data or now >= deadline:
                    return data
                wake = min(t for t in (deadline, self._next_due(), self._next_reboot, self._next_unplug) if t is not None)
                self._cond.wait(max(0.0, wake - now))

    def write(self, data: bytes) -> None:
        with self._cond:
            self._tick(self._clock())
            self._check_usable()
            self.board.receive(bytes(data))
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._open = False
            self._lost = False
            self._out.clear()
            self._next_reboot = self._next_unplug = None
            self._cond.notify_all()

    # --- pulling the cable by hand (hcl.testing)

    def unplug(self) -> None:
        """Pull the cable: an open port fails like a real one, and opening fails
        until replug(). Unlike unplug_every, it happens exactly now."""
        with self._cond:
            self._unplugged_until = float("inf")
            if self._open:
                self._lost = True
                self._out.clear()
                self._next_unplug = self._next_reboot = None
            self._cond.notify_all()

    def replug(self) -> None:
        """Plug the cable back in: the next open() works and powers the board on."""
        with self._cond:
            self._unplugged_until = 0.0
            self._cond.notify_all()

    @property
    def plugged(self) -> bool:
        with self._cond:
            return not self._lost and self._clock() >= self._unplugged_until

    # --- inside

    def _schedule(self, delay: float, data: bytes) -> None:
        heapq.heappush(self._out, (self._clock() + delay, next(self._order), data))
        self._cond.notify_all()

    def _next_due(self) -> float | None:
        return self._out[0][0] if self._out else None

    def _take_due(self, now: float, max_bytes: int) -> bytes:
        chunks = []
        size = 0
        while self._out and self._out[0][0] <= now and size < max_bytes:
            due, order, data = heapq.heappop(self._out)
            room = max_bytes - size
            if len(data) > room:
                heapq.heappush(self._out, (due, order, data[room:]))
                data = data[:room]
            chunks.append(data)
            size += len(data)
        return b"".join(chunks)

    def _tick(self, now: float) -> None:
        if not self._open or self._lost:
            return
        if self._next_unplug is not None and now >= self._next_unplug:
            self._lost = True
            self._unplugged_until = now + self.options.unplug_for
            self._out.clear()
            self._next_unplug = self._next_reboot = None
            return
        if self._next_reboot is not None and now >= self._next_reboot:
            self._next_reboot = now + self.options.reboot_every
            self._out.clear()
            self.board.power_on()

    def _check_usable(self) -> None:
        if not self._open:
            raise TransportError("port is closed")
        if self._lost:
            raise TransportError("simulated board was unplugged")
