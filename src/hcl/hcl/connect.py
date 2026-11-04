"""open_link(): a link from a URL (docs/hcl.md 3.1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields

from hcl.link import Link, LinkOptions
from hcl.transport.base import Transport
from hcl.transport.serial import SerialTransport
from hcl.transport.sim import SimTransport

DEFAULT_BAUD = 115200


def open_link(url: str = "sim", *, baud: int = DEFAULT_BAUD, **options: object) -> Link:
    """A link to the board at `url`. Nothing is opened until `await link.start()`.

        sim                                   the simulated board
        sim?latency_ms=8&drop=0.02            the simulated board with faults
        /dev/ttyUSB0                          a real port (WSL)
        socket://host.docker.internal:7777    through the Windows bridge (notebook)

    `options` are the link's timings (LinkOptions: ack_timeout_ms, hello_timeout_ms,
    keepalive_ms, max_fps, ...). An unknown option or a bad URL raises ValueError.
    """
    link_options = make_link_options(options)
    transport = open_transport(url, baud=baud)
    return Link(transport, url=url, options=link_options)


def make_link_options(options: Mapping[str, object]) -> LinkOptions:
    """LinkOptions from keyword options. An unknown option raises ValueError."""
    known = {f.name for f in fields(LinkOptions)}
    unknown = sorted(set(options) - known)
    if unknown:
        raise ValueError(f"unknown link option(s) {', '.join(unknown)}; known: baud, {', '.join(sorted(known))}")
    return LinkOptions(**options)  # type: ignore[arg-type]


def open_transport(url: str, *, baud: int = DEFAULT_BAUD) -> Transport:
    """Just the byte pipe to the board, not opened yet. For tools that must talk
    to the board without the link in between (hcl.tools.repl)."""
    if not url:
        raise ValueError("no board URL given, e.g. 'sim' or '/dev/ttyUSB0'")
    if url == "sim" or url.startswith("sim?"):
        return SimTransport.from_url(url)
    return SerialTransport(url, baud=baud)
