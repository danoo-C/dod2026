"""What all tools share: the --url option, clean Ctrl-C, and how status and events look."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable

from hcl import (
    Connected,
    DeviceInfo,
    DeviceLog,
    Disconnected,
    Incompatible,
    Link,
    LinkEvent,
    LinkState,
    LinkStatus,
    RawText,
)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # like any program stopped with Ctrl-C


def make_parser(prog: str, description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=f"./dod hcl {prog}", description=description)
    p.add_argument("--url", default=os.environ.get("DOD_SERIAL") or "sim",
                   help="the board: sim, sim?…, /dev/ttyUSB0 or socket://host:port "
                        "(default: $DOD_SERIAL, else sim)")
    p.add_argument("--baud", type=int, default=115200, help="serial speed (default 115200)")
    return p


def run(amain: Callable[[argparse.Namespace], Awaitable[int]], args: argparse.Namespace) -> int:
    """Run a tool's async main. Ctrl-C ends it cleanly, a bad URL or option is a usage error."""
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return EXIT_INTERRUPTED
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE


async def wait_connected(link: Link, timeout: float) -> DeviceInfo | None:
    """The board's info once it is connected, or None after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = link.status
        if s.state is LinkState.CONNECTED and s.device is not None:
            return s.device
        await asyncio.sleep(0.02)
    return None


def stamp(t: float | None = None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


def describe_device(d: DeviceInfo) -> str:
    sim = ", simulated" if d.simulated else ""
    return f"firmware {d.firmware_str}{sim}, {d.led_count} LEDs, {d.color_order}, protocol {d.protocol}"


def describe_status(s: LinkStatus) -> str:
    rtt = "-" if s.rtt_ms is None else f"{s.rtt_ms:.1f} ms ({s.rtt_min_ms:.1f}–{s.rtt_max_ms:.1f})"
    parts = [
        f"{s.state.value:<12}",
        f"{s.fps:5.1f} fps",
        f"rtt {rtt}",
        f"sent {s.frames_sent}",
        f"acked {s.frames_acked}",
        f"timeouts {s.ack_timeouts}",
        f"tx {s.bytes_tx} B",
        f"rx {s.bytes_rx} B",
        f"garbage {s.garbage_bytes} B",
        f"reconnects {s.reconnects}",
    ]
    line = " | ".join(parts)
    if s.state is not LinkState.CONNECTED and s.last_error:
        line += f" | {s.last_error}"
    return line


def describe_event(e: LinkEvent) -> str:
    if isinstance(e, Connected):
        what = "rebooted" if e.rebooted else "connected"
        return f"board {what}: {describe_device(e.device)}"
    if isinstance(e, Disconnected):
        return f"board lost: {e.reason}"
    if isinstance(e, Incompatible):
        return f"incompatible board: {e.reason}"
    if isinstance(e, DeviceLog):
        return f"board says ({e.level.name.lower()}): {e.text}"
    if isinstance(e, RawText):
        return f"board prints: {e.line}"
    return repr(e)
