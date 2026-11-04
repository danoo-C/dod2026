"""For tests above the HCL: a link to the simulated board, and a handle on the board.

Design: docs/hcl.md 3.6. The backend's tests use this instead of reaching
into hcl.transport, which is not part of the API:

    from hcl.testing import sim_link

    link, board = sim_link()              # fast timings, a healthy board
    await link.start()
    link.submit(frame)
    ... board.strip_rgb() == frame.strip  # what the board shows, in RGB
    board.unplug(); board.replug()        # pull the cable, exactly now
    await link.stop()
"""

from __future__ import annotations

from types import MappingProxyType

from hcl.connect import make_link_options
from hcl.link import Link
from hcl.transport.sim import Picture, SimTransport

# Timings short enough for tests: a lost board is noticed and reconnected
# within a few hundred milliseconds instead of seconds.
FAST = MappingProxyType(dict(
    ack_timeout_ms=40,
    hello_timeout_ms=300,
    keepalive_ms=100,
    ping_interval_ms=50,
    incompatible_ping_ms=100,
    backoff_ms=(20, 40),
))


class SimBoard:
    """The simulated board behind a sim_link(): what it shows, and its cable."""

    def __init__(self, transport: SimTransport) -> None:
        self._t = transport

    @property
    def led_count(self) -> int:
        return self._t.options.led_count

    def strip_rgb(self) -> bytes | None:
        """The strip it shows, converted back to RGB; None before the first frame."""
        return self._t.board.strip_rgb()

    @property
    def picture(self) -> Picture | None:
        """The last frame as received: strip in the board's colour order, matrix, brightness."""
        return self._t.board.picture

    @property
    def frames_received(self) -> int:
        """Frames shown since the last power-on."""
        return self._t.board.frames_received

    @property
    def boots(self) -> int:
        """How often it powered on: once per connection, plus reboots."""
        return self._t.board.boots

    @property
    def idle(self) -> bool:
        """True while it would show its own idle animation (no frame for 3 s)."""
        return self._t.board.idle

    @property
    def plugged(self) -> bool:
        return self._t.plugged

    def unplug(self) -> None:
        """Pull the cable now. The link sees a lost port and keeps trying to reconnect."""
        self._t.unplug()

    def replug(self) -> None:
        """Plug it back in. The link reconnects on its next attempt."""
        self._t.replug()


def sim_link(url: str = "sim", **timings: object) -> tuple[Link, SimBoard]:
    """A link to a simulated board, not started yet, and a handle on that board.

    `url` is a sim URL with the board's options (`sim?led_count=12`, see
    docs/hcl.md 6). `timings` override FAST; an unknown one raises ValueError,
    like open_link().
    """
    transport = SimTransport.from_url(url)
    link = Link(transport, url=url, options=make_link_options({**FAST, **timings}))
    return link, SimBoard(transport)
