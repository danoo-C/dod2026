"""./dod hcl bench – how fast the link really is: frames as fast as the board ACKs them.

Reports frames per second, round-trip times and problems, and ends with a
verdict: the show runs at 30 fps, so the link should manage 45 (30 plus
room to spare) with no ACK timeouts and no reconnects (docs/hcl.md 9).
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from hcl import Frame, Link, open_link
from hcl.tools.common import EXIT_FAIL, EXIT_OK, describe_device, make_parser, run, wait_connected

CONNECT_TIMEOUT = 10.0
NEEDED_FPS = 45.0
SAMPLE_EVERY = 1.0  # the link's status averages over 2 s; sampling every 1 s misses nothing


@dataclass
class Result:
    seconds: float
    frames_acked: int
    ack_timeouts: int
    reconnects: int
    rtt_min_ms: float | None
    rtt_avg_ms: float | None
    rtt_max_ms: float | None
    bytes_tx: int

    @property
    def fps(self) -> float:
        return self.frames_acked / self.seconds if self.seconds else 0.0

    def problems(self) -> list[str]:
        found = []
        if self.fps < NEEDED_FPS:
            found.append(f"only {self.fps:.1f} fps, needs {NEEDED_FPS:g}")
        if self.ack_timeouts:
            found.append(f"{self.ack_timeouts} ACK timeouts")
        if self.reconnects:
            found.append(f"{self.reconnects} reconnects")
        return found


async def bench(link: Link, seconds: float, out: Callable[[str], None] = print) -> int:
    await link.start()
    try:
        device = await wait_connected(link, CONNECT_TIMEOUT)
        if device is None:
            out(f"no board answered within {CONNECT_TIMEOUT:g} s: {link.status.last_error or 'no reason known'}")
            return EXIT_FAIL
        out(f"board: {describe_device(device)}")
        out(f"sending frames as fast as the board answers, for {seconds:g} s …")
        result = await _measure(link, device.led_count, seconds)
    finally:
        await link.stop()

    def ms(v: float | None) -> str:
        return "-" if v is None else f"{v:.1f} ms"

    out(f"frames acknowledged  {result.frames_acked} in {result.seconds:.1f} s = {result.fps:.1f} fps")
    out(f"round trip           min {ms(result.rtt_min_ms)}, avg {ms(result.rtt_avg_ms)}, max {ms(result.rtt_max_ms)}")
    out(f"sent                 {result.bytes_tx / result.seconds / 1000:.1f} kB/s")
    out(f"ACK timeouts         {result.ack_timeouts}")
    out(f"reconnects           {result.reconnects}")
    problems = result.problems()
    if problems:
        out("FAIL: " + "; ".join(problems))
        return EXIT_FAIL
    out(f"PASS: {result.fps:.0f} fps is enough for the 30 fps show")
    return EXIT_OK


async def _measure(link: Link, led_count: int, seconds: float) -> Result:
    before = link.status
    rtt_min = rtt_max = None
    avgs: list[tuple[float, float]] = []  # (average, weight = fps) per sample
    start = time.monotonic()
    next_sample = start + SAMPLE_EVERY
    n = 0
    while (now := time.monotonic()) < start + seconds:
        # a new frame every time the event loop comes round; the link sends the newest
        n += 1
        link.submit(Frame(strip=bytes([n % 256, 0, 0]) * led_count, matrix=bytes([n % 256] * 8), brightness=n % 16))
        if now >= next_sample:
            next_sample += SAMPLE_EVERY
            s = link.status
            if s.rtt_ms is not None:
                rtt_min = s.rtt_min_ms if rtt_min is None else min(rtt_min, s.rtt_min_ms)
                rtt_max = s.rtt_max_ms if rtt_max is None else max(rtt_max, s.rtt_max_ms)
                avgs.append((s.rtt_ms, s.fps))
        await asyncio.sleep(0.001)
    elapsed = time.monotonic() - start
    after = link.status
    weight = sum(w for _, w in avgs)
    return Result(
        seconds=elapsed,
        frames_acked=after.frames_acked - before.frames_acked,
        ack_timeouts=after.ack_timeouts - before.ack_timeouts,
        reconnects=after.reconnects - before.reconnects,
        rtt_min_ms=rtt_min,
        rtt_avg_ms=sum(a * w for a, w in avgs) / weight if weight else None,
        rtt_max_ms=rtt_max,
        bytes_tx=after.bytes_tx - before.bytes_tx,
    )


def main(argv: list[str] | None = None) -> int:
    p = make_parser("bench", __doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=20.0, help="how long to measure (default 20)")
    p.add_argument("--max-fps", type=float, default=1000.0,
                   help="the link's frame rate cap during the test (default 1000, i.e. as fast as possible)")
    args = p.parse_args(argv)
    if args.seconds <= 0:
        p.error("--seconds must be positive")

    async def amain(a: argparse.Namespace) -> int:
        return await bench(open_link(a.url, baud=a.baud, max_fps=a.max_fps), a.seconds)

    return run(amain, args)


if __name__ == "__main__":
    raise SystemExit(main())
