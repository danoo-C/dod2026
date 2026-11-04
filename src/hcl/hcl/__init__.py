"""Hardware communication layer: gets the backend's frames onto the ESP32.

Design: docs/hcl.md. Everything the backend may use is exported here; the
modules behind it (protocol, transports, the link's internals) are not part
of the API and can change.
"""

from hcl.types import (
    MAX_BRIGHTNESS,
    MAX_LEDS,
    MATRIX_ROWS,
    Connected,
    DeviceInfo,
    DeviceLog,
    Disconnected,
    Frame,
    Incompatible,
    LinkEvent,
    LinkState,
    LinkStatus,
    LogLevel,
    RawText,
)
from hcl.link import EventStream, Link, LinkOptions
from hcl.connect import open_link

__all__ = [
    "open_link",
    "Link",
    "LinkOptions",
    "EventStream",
    "Frame",
    "DeviceInfo",
    "LinkState",
    "LinkStatus",
    "LogLevel",
    "LinkEvent",
    "Connected",
    "Disconnected",
    "DeviceLog",
    "RawText",
    "Incompatible",
    "MATRIX_ROWS",
    "MAX_BRIGHTNESS",
    "MAX_LEDS",
]
