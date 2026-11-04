"""./dod hcl monitor – watch the link: a status line every second and every event.

The first thing to run when something is wrong (docs/hcl.md 9). By default it
only watches and sends nothing, so it doesn't change what the board shows;
--send adds a dim test frame, so fps and round-trip times mean something.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections.abc import Callable

from hcl import Frame, Link, open_link
from hcl.tools.common import EXIT_OK, describe_event, describe_status, make_parser, run, stamp

SEND_FPS = 30


def breathing_frame(led_count: int, t: float) -> Frame:
    """A dim, slowly breathing blue: easy on the eyes, clearly alive."""
    level = int(10 + 30 * (0.5 + 0.5 * math.sin(t * 2)))
    return Frame(strip=bytes([0, 0, level]) * led_count, matrix=bytes([0x18, 0x3C, 0x7E, 0xFF] * 2), brightness=1)


async def monitor(link: Link, seconds: float | None, send: bool, out: Callable[[str], None] = print) -> int:
    events = link.events()

    async def print_events() -> None:
        async for e in events:
            out(f"{stamp(e.at)}  {describe_event(e)}")

    async def send_frames() -> None:
        start = time.monotonic()
        while True:
            device = link.status.device
            if device is not None:
                link.submit(breathing_frame(device.led_count, time.monotonic() - start))
            await asyncio.sleep(1 / SEND_FPS)

    out(f"monitoring {link.status.url}{' (sending a test frame)' if send else ''}, Ctrl-C to stop")
    await link.start()
    tasks = [asyncio.create_task(print_events())]
    if send:
        tasks.append(asyncio.create_task(send_frames()))
    try:
        deadline = None if seconds is None else time.monotonic() + seconds
        while deadline is None or time.monotonic() < deadline:
            await asyncio.sleep(1 if deadline is None else min(1, max(0, deadline - time.monotonic())))
            out(f"{stamp()}  {describe_status(link.status)}")
    finally:
        await link.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = make_parser("monitor", __doc__.splitlines()[0])
    p.add_argument("--send", action="store_true", help="send a dim breathing test frame at 30 fps")
    p.add_argument("--seconds", type=float, help="stop after this many seconds (default: until Ctrl-C)")
    args = p.parse_args(argv)

    async def amain(a: argparse.Namespace) -> int:
        return await monitor(open_link(a.url, baud=a.baud), a.seconds, a.send)

    return run(amain, args)


if __name__ == "__main__":
    raise SystemExit(main())
