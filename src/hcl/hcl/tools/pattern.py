"""./dod hcl pattern – wiring test: lights every LED and every 8x8 pixel in a known order.

It prints what should be visible at each moment, so a wrong colour order, a
dead LED or a swapped 8x8 wire is easy to spot (docs/hcl.md 9).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable

from hcl import MAX_BRIGHTNESS, Frame, Link, open_link
from hcl.tools.common import EXIT_FAIL, EXIT_OK, describe_device, make_parser, run, wait_connected

CONNECT_TIMEOUT = 10.0
COLORS = [("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255))]
STRIP_LEVEL = 60  # out of 255: bright enough to see, easy on the power supply
WALK_COLOR = (STRIP_LEVEL, STRIP_LEVEL, STRIP_LEVEL)
NO_MATRIX = bytes(8)


def steps(led_count: int) -> list[tuple[str, Frame, float]]:
    """(what should be visible, frame, seconds) for the whole pattern."""
    off = bytes(3 * led_count)
    out: list[tuple[str, Frame, float]] = []

    for name, (r, g, b) in COLORS:
        level = lambda v: v * STRIP_LEVEL // 255  # noqa: E731
        strip = bytes([level(r), level(g), level(b)]) * led_count
        hint = " (if not, COLOR_ORDER in src/hcl/esp/config.py is wrong)" if name != "RED" else \
               " (if it is green, COLOR_ORDER in src/hcl/esp/config.py is wrong)"
        out.append((f"strip: every LED {name}{hint}", Frame(strip=strip, matrix=NO_MATRIX, brightness=0), 1.5))

    for i in range(led_count):
        strip = bytearray(off)
        strip[3 * i : 3 * i + 3] = bytes(WALK_COLOR)
        out.append((f"strip: only LED {i + 1} of {led_count} white", Frame(strip=bytes(strip), matrix=NO_MATRIX, brightness=0), 0.3))

    for row in range(8):
        matrix = bytes(0xFF if r == row else 0 for r in range(8))
        out.append((f"8x8: only row {row + 1} (from the top) on", Frame(strip=off, matrix=matrix, brightness=4), 0.25))
    for col in range(8):
        matrix = bytes([0x80 >> col] * 8)
        out.append((f"8x8: only column {col + 1} (from the left) on", Frame(strip=off, matrix=matrix, brightness=4), 0.25))

    for b in range(MAX_BRIGHTNESS + 1):
        out.append((f"8x8: all pixels, brightness {b} of {MAX_BRIGHTNESS}", Frame(strip=off, matrix=bytes([0xFF] * 8), brightness=b), 0.15))

    out.append(("everything off", Frame.blank(led_count), 0.5))
    return out


async def pattern(link: Link, speed: float = 1.0, out: Callable[[str], None] = print) -> int:
    await link.start()
    try:
        device = await wait_connected(link, CONNECT_TIMEOUT)
        if device is None:
            out(f"no board answered within {CONNECT_TIMEOUT:g} s: {link.status.last_error or 'no reason known'}")
            return EXIT_FAIL
        out(f"board: {describe_device(device)}")
        for what, frame, seconds in steps(device.led_count):
            out(f"  {what}")
            link.submit(frame)
            await asyncio.sleep(seconds / speed)
        out("done")
        return EXIT_OK
    finally:
        await link.stop()


def main(argv: list[str] | None = None) -> int:
    p = make_parser("pattern", __doc__.splitlines()[0])
    p.add_argument("--speed", type=float, default=1.0, help="faster (2 = twice as fast) or slower (0.5)")
    args = p.parse_args(argv)
    if args.speed <= 0:
        p.error("--speed must be positive")

    async def amain(a: argparse.Namespace) -> int:
        return await pattern(open_link(a.url, baud=a.baud), a.speed)

    return run(amain, args)


if __name__ == "__main__":
    raise SystemExit(main())
