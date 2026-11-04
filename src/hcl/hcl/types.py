"""The types the backend sees (docs/hcl.md, sections 3.2 to 3.5)."""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

from hcl import protocol

MATRIX_ROWS = protocol.MATRIX_ROWS
MAX_BRIGHTNESS = protocol.MAX_BRIGHTNESS
# as many LEDs as fit into one FRAME message
MAX_LEDS = (protocol.MAX_PAYLOAD - protocol.FRAME_FIXED) // 3


@dataclass(frozen=True)
class Frame:
    """One picture: the whole strip, the whole 8x8 and its brightness.

    strip      3 bytes per LED, R G B, in strip order
    matrix     8 bytes, row 0 = top, bit 7 = leftmost pixel
    brightness 0-15, for the whole matrix (the MAX7219 has one setting)

    A wrong shape raises ValueError right away: that is always a bug in the
    caller. Whether the LED count matches the connected board is checked by
    the link, when the frame is submitted.
    """

    strip: bytes
    matrix: bytes
    brightness: int

    def __post_init__(self) -> None:
        strip = _as_bytes("strip", self.strip)
        matrix = _as_bytes("matrix", self.matrix)
        if not strip:
            raise ValueError("strip is empty")
        if len(strip) % 3:
            raise ValueError(f"strip must be 3 bytes per LED, got {len(strip)} bytes")
        if len(strip) // 3 > MAX_LEDS:
            raise ValueError(f"strip has {len(strip) // 3} LEDs, at most {MAX_LEDS} fit into one frame")
        if len(matrix) != MATRIX_ROWS:
            raise ValueError(f"matrix must be {MATRIX_ROWS} bytes, got {len(matrix)}")
        if not isinstance(self.brightness, int) or isinstance(self.brightness, bool):
            raise ValueError(f"brightness must be an int, got {self.brightness!r}")
        if not 0 <= self.brightness <= MAX_BRIGHTNESS:
            raise ValueError(f"brightness must be 0-{MAX_BRIGHTNESS}, got {self.brightness}")
        # keep our own immutable copy, so changing the caller's buffer later changes nothing
        object.__setattr__(self, "strip", strip)
        object.__setattr__(self, "matrix", matrix)

    @property
    def led_count(self) -> int:
        return len(self.strip) // 3

    @classmethod
    def blank(cls, led_count: int) -> Frame:
        """Everything off."""
        return cls(strip=bytes(3 * led_count), matrix=bytes(MATRIX_ROWS), brightness=0)


def _as_bytes(name: str, value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise ValueError(f"{name} must be bytes, got {type(value).__name__}")


@dataclass(frozen=True)
class DeviceInfo:
    """What the board said about itself in its HELLO."""

    protocol: int
    firmware: tuple[int, int, int]
    led_count: int
    color_order: str
    simulated: bool = False  # True for the simulated board (docs/hcl.md 6)

    @property
    def firmware_str(self) -> str:
        return ".".join(str(n) for n in self.firmware)


class LinkState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class LinkStatus:
    """A snapshot of the link, safe to keep and pass around (docs/hcl.md 3.4).
    Times are Unix timestamps (seconds), counters count since start()."""

    state: LinkState = LinkState.DISCONNECTED
    url: str = ""
    device: DeviceInfo | None = None
    connected_since: float | None = None
    fps: float = 0.0
    rtt_ms: float | None = None  # average round trip, last 2 s
    rtt_min_ms: float | None = None
    rtt_max_ms: float | None = None
    frames_sent: int = 0
    frames_acked: int = 0
    frames_replaced: int = 0
    ack_timeouts: int = 0
    garbage_bytes: int = 0
    reconnects: int = 0
    bytes_tx: int = 0
    bytes_rx: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-ready data, for the backend's /api/status."""
        d = dataclasses.asdict(self)
        d["state"] = self.state.value
        if self.device is not None:
            d["device"]["firmware"] = self.device.firmware_str
        return d


class LogLevel(IntEnum):
    INFO = protocol.LOG_INFO
    WARN = protocol.LOG_WARN
    ERROR = protocol.LOG_ERROR

    @classmethod
    def from_wire(cls, value: int) -> LogLevel:
        """An unknown level from the board is treated as an error, so it is not missed."""
        try:
            return cls(value)
        except ValueError:
            return cls.ERROR


# --- events (docs/hcl.md 3.5) -----------------------------------------------
# Every event carries the time it happened (`at`, a Unix timestamp).


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class Connected:
    """HELLO received. rebooted=True: the board restarted while connected."""

    device: DeviceInfo
    rebooted: bool = False
    at: float = field(default_factory=_now, kw_only=True)


@dataclass(frozen=True)
class Disconnected:
    """The port was lost, or the board stopped answering."""

    reason: str
    at: float = field(default_factory=_now, kw_only=True)


@dataclass(frozen=True)
class DeviceLog:
    """A LOG message from the board."""

    level: LogLevel
    text: str
    at: float = field(default_factory=_now, kw_only=True)


@dataclass(frozen=True)
class RawText:
    """A line of readable text outside any message: the boot banner, a crash traceback."""

    line: str
    at: float = field(default_factory=_now, kw_only=True)


@dataclass(frozen=True)
class Incompatible:
    """The board speaks another protocol version; nothing is sent to it."""

    reason: str
    protocol: int
    at: float = field(default_factory=_now, kw_only=True)


LinkEvent = Connected | Disconnected | DeviceLog | RawText | Incompatible
