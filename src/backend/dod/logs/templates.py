"""What the fake terminal says (tech-spec 4.5): real events dressed up, filler
from templates, and bursts. Only text here; when lines are sent is decided by
dod.logs.generator.

A line is (tag, level, text). Levels are the four the page has colours for:
DEBUG, INFO, OK, WARN. Real errors never come here (they go to `docker logs`
and the status badge), so there is no ERROR.

Everything random takes a `random.Random`, so a fixed seed gives the same
lines in tests.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from dod.bus import (
    BoardConnected,
    BoardLog,
    BoardLost,
    DrawingChanged,
    Event,
    ParamChanged,
    PresetChanged,
    QueueJoined,
    QueueLeft,
    SongEnded,
    SongStarted,
    TurnEnded,
    TurnStarted,
)
from dod.control.sessions import short

Line = tuple[str, str, str]  # (tag, level, text)

LEVELS = ("DEBUG", "INFO", "OK", "WARN")
MAX_TEXT = 120  # characters; longer text from the board is cut
HEX_BYTES = 10  # bytes shown in a hex dump


@dataclass(frozen=True)
class Facts:
    """The real numbers the lines can use, read when a line is written.
    Everything is optional: before the board answers there are no frames."""

    frame_no: int = 0  # the render loop's frame counter, up 30 a second
    bytes_tx: int = 0  # to the board since the link started (updated once a second)
    link_fps: float = 0.0  # frames the board acknowledged per second
    render_fps: float = 0.0
    rtt_ms: float | None = None
    led_count: int = 0
    mode: str = "idle"
    preset: str = ""
    connections: int = 0
    waiting: int = 0
    frame: bytes = b""  # the last frame sent to the board: strip, then the 8x8
    beat: bool | None = None  # from the music mode (plan step 8); None until then


@dataclass(frozen=True)
class Template:
    tag: str
    level: str
    fill: Callable[[random.Random, Facts], str | None]  # None: can't be written now, pick another
    weight: int = 1


def who(by: str | None) -> str:
    return "main screen" if by == "main" else f"session {by}…" if by else "system"


def session(public_id: str) -> str:
    return f"session {short(public_id)}…"


def hexdump(data: bytes) -> str:
    shown = " ".join(f"{b:02x}" for b in data[:HEX_BYTES])
    return shown + (" …" if len(data) > HEX_BYTES else "")


def bar(fraction: float, width: int = 20) -> str:
    done = round(fraction * width)
    return f"[{'#' * done}{'-' * (width - done)}] {round(fraction * 100):3d}%"


def _clip(text: str) -> str:
    text = " ".join(text.split())  # one line, whatever the board sent
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


# --- real events --------------------------------------------------------------


def event_lines(event: Event) -> list[Line]:
    """The lines for one real event; [] for events that stay out of the terminal
    (BoardText and BoardIncompatible are real problems: docker logs and the badge)."""
    match event:
        case PresetChanged(preset=preset, by=by):
            return [("engine", "INFO", f"preset -> {preset} ({who(by)})"),
                    ("rgb-core", "DEBUG", f"shader graph rebuilt for '{preset}'")]
        case ParamChanged(preset=preset, name=name, value=value, by=by):
            shown = f"{value:.2f}" if isinstance(value, float) else str(value).lower()
            return [("engine", "INFO", f"{preset}.{name} = {shown} ({who(by)})")]
        case DrawingChanged(by=by):
            return [("lattice", "INFO", f"8x8 bitmap uploaded ({who(by)})")]
        case SongStarted(song=song, title=title, by=by):
            return [("media", "INFO", f"stream open: {_clip(title)} [{song}] ({who(by)})")]
        case SongEnded(song=song, reason=reason):
            return [("media", "INFO", f"stream closed: [{song}] ({reason})")]
        case TurnStarted(session=s, waiting=waiting):
            return [("queue", "INFO", f"{session(s)} acquired control ({waiting} waiting)")]
        case TurnEnded(session=s, reason=reason):
            return [("queue", "INFO", f"{session(s)} released control ({reason})")]
        case QueueJoined(session=s, position=position):
            return [("queue", "INFO", f"{session(s)} enqueued at #{position}")]
        case QueueLeft(session=s, reason="gone"):
            return [("queue", "WARN", f"{session(s)} timed out, dropped from queue")]
        case QueueLeft(session=s):
            return [("queue", "INFO", f"{session(s)} left the queue")]
        case BoardConnected(led_count=n, firmware=firmware, simulated=simulated, rebooted=rebooted):
            lines: list[Line] = [
                ("esp32", "INFO", f"handshake ok: fw {firmware}, {n} leds{' (sim)' if simulated else ''}"),
                ("serial", "OK", "link up"),
            ]
            if rebooted:
                lines.insert(0, ("esp32", "WARN", "device rebooted, state lost, resyncing"))
            return lines
        case BoardLost():
            return [("serial", "WARN", "link down, retrying")]
        case BoardLog(level=level, text=text):
            return [("esp32", level if level in LEVELS else "WARN", _clip(text))]
        case _:
            return []


# --- filler -------------------------------------------------------------------


def _frame_committed(r: random.Random, f: Facts) -> str | None:
    if not f.frame_no or not f.frame:
        return None
    return f"frame {f.frame_no % 1_000_000:06d} committed ({len(f.frame)} B, sum 0x{sum(f.frame) & 0xFF:02x})"


def _tx(r: random.Random, f: Facts) -> str | None:
    return f"tx {hexdump(f.frame)}" if f.frame else None


def _fps(r: random.Random, f: Facts) -> str | None:
    if not f.render_fps:
        return None
    return f"render {f.render_fps:.1f} fps, link {f.link_fps:.1f} fps, {f.led_count} leds"


def _rtt(r: random.Random, f: Facts) -> str | None:
    return None if f.rtt_ms is None else f"ping {f.rtt_ms:.1f} ms"


def _bytes(r: random.Random, f: Facts) -> str | None:
    return f"{f.bytes_tx / 1024:.1f} KiB out since boot" if f.bytes_tx else None


def _preset(r: random.Random, f: Facts) -> str | None:
    if f.mode == "manual" and f.preset:
        return f"pipeline '{f.preset}' running, {r.randint(3, 9)} stages"
    if f.mode == "music":
        return "pipeline 'spectral' running, audio-locked"
    return "pipeline 'idle' running, low power"


def _beat(r: random.Random, f: Facts) -> str | None:
    if f.beat is None:
        return None
    return f"32 bins ok, peak {r.choice((56, 84, 112, 168, 224))} Hz, beat={int(f.beat)}"


def _clients(r: random.Random, f: Facts) -> str | None:
    return f"{f.connections} clients attached, {f.waiting} in queue" if f.connections else None


def _fixed(text: Callable[[random.Random], str]) -> Callable[[random.Random, Facts], str]:
    return lambda r, f: text(r)


FILLER: tuple[Template, ...] = (
    # the real numbers
    Template("rgb-core", "INFO", _frame_committed, weight=4),
    Template("serial", "DEBUG", _tx, weight=3),
    Template("rgb-core", "INFO", _fps, weight=2),
    Template("serial", "DEBUG", _rtt),
    Template("serial", "INFO", _bytes),
    Template("engine", "INFO", _preset),
    Template("fft", "INFO", _beat, weight=3),
    Template("gateway", "INFO", _clients),
    # made up
    Template("photon-bus", "WARN", _fixed(lambda r: f"coherence drift {r.uniform(0.01, 0.09):.2f}%, recalibrating")),
    Template("photon-bus", "INFO", _fixed(lambda r: f"lane {r.randint(0, 7)} phase locked ({r.uniform(0.2, 2.5):.1f} ns)")),
    Template("photon-bus", "OK", _fixed(lambda r: "recalibration done")),
    Template("lattice", "INFO", _fixed(lambda r: f"matrix sync {bar(r.random())}")),
    Template("lattice", "DEBUG", _fixed(lambda r: f"row {r.randint(0, 7)} refresh {r.randint(780, 820)} Hz")),
    Template("thermal", "INFO", _fixed(lambda r: f"die {r.uniform(41, 58):.1f} °C, fan {r.randint(1800, 2600)} rpm")),
    Template("thermal", "WARN", _fixed(lambda r: f"hotspot zone {r.randint(1, 4)} at {r.uniform(61, 67):.1f} °C, throttling 2%")),
    Template("sched", "DEBUG", _fixed(lambda r: f"tick jitter {r.uniform(0.05, 0.9):.2f} ms (p99 {r.uniform(1, 2.5):.2f})")),
    Template("sched", "INFO", _fixed(lambda r: f"worker pool {r.randint(4, 12)}/16 busy")),
    Template("kernel", "DEBUG", _fixed(lambda r: f"irq {r.randint(16, 63)} serviced in {r.randint(2, 40)} µs")),
    Template("kernel", "INFO", _fixed(lambda r: f"page cache {r.randint(60, 98)}% hit")),
    Template("dsp", "DEBUG", _fixed(lambda r: f"fir taps {r.choice((64, 128, 256))}, window hann, overlap {r.choice((50, 75))}%")),
    Template("dsp", "INFO", _fixed(lambda r: f"gain stage {r.uniform(-6, 3):+.1f} dB")),
    Template("cache", "INFO", _fixed(lambda r: f"lut {r.randint(0, 15):x} warm ({r.randint(2, 64)} KiB)")),
    Template("cache", "DEBUG", _fixed(lambda r: f"evicted {r.randint(1, 40)} stale palettes")),
    Template("neural", "INFO", _fixed(lambda r: f"mood vector [{', '.join(f'{r.uniform(-1, 1):.2f}' for _ in range(4))}]")),
    Template("neural", "DEBUG", _fixed(lambda r: f"inference {r.uniform(1.5, 9.5):.1f} ms, confidence {r.uniform(0.81, 0.99):.2f}")),
    Template("gateway", "DEBUG", _fixed(lambda r: f"heartbeat seq {r.randint(1000, 99999)} ok")),
    Template("rgb-core", "OK", _fixed(lambda r: f"gamma table verified (crc 0x{r.getrandbits(16):04x})")),
    Template("rgb-core", "DEBUG", _fixed(lambda r: f"dither seed 0x{r.getrandbits(32):08x}")),
    Template("power", "INFO", _fixed(lambda r: f"rail 5V0 {r.uniform(4.92, 5.08):.2f} V, budget {r.randint(20, 85)}%")),
    Template("power", "OK", _fixed(lambda r: "brownout guard armed")),
)


def filler(r: random.Random, facts: Facts) -> Line:
    """One filler line. A template that can't be written now (no frames yet)
    gives way to another; the made-up ones always can."""
    weights = [t.weight for t in FILLER]
    for _ in range(8):
        template = r.choices(FILLER, weights)[0]
        text = template.fill(r, facts)
        if text is not None:
            return template.tag, template.level, text
    return "sched", "DEBUG", f"tick jitter {r.uniform(0.05, 0.9):.2f} ms"


# --- bursts -------------------------------------------------------------------

BURST_MIN, BURST_MAX = 30, 50

MODULES = ("photon-bus", "lattice", "rgb-core", "fft", "dsp", "neural", "thermal", "cache", "power", "sched")
STAGES = ("compiling shaders", "loading palettes", "warming lut", "syncing lattice", "training mood model",
          "aligning phase", "mapping leds", "priming spectral buffers")

BURST_TITLES = {
    "loading": "compute graph",
    "song": "spectral pipeline",
}


def burst(kind: str, r: random.Random, facts: Facts) -> list[Line]:
    """30-50 lines of heavy-looking work: a header, modules loading, progress
    bars, checks, done. `kind` is 'loading' or 'song'."""
    title = BURST_TITLES.get(kind, "compute graph")
    n = r.randint(BURST_MIN, BURST_MAX)
    lines: list[Line] = [("sched", "INFO", f"=== rebuilding {title} ===")]
    end = [("sched", "OK", f"{title} ready in {r.uniform(0.9, 1.9):.2f} s")]
    body: list[Line] = []
    modules = r.sample(MODULES, len(MODULES))
    stages = r.sample(STAGES, len(STAGES))
    while len(lines) + len(body) + len(end) < n:
        room = n - len(lines) - len(body) - len(end)
        pick = r.random()
        if pick < 0.4 and modules:
            module = modules.pop()
            body.append(("kernel", "INFO", f"module {module} loaded (0x{r.getrandbits(24):06x}, {r.randint(4, 96)} KiB)"))
        elif pick < 0.75 and stages and room >= 4:
            stage, tag = stages.pop(), r.choice(("lattice", "rgb-core", "neural", "dsp"))
            steps = min(room - 1, r.randint(3, 6))
            for i in range(1, steps + 1):
                body.append((tag, "INFO", f"{stage} {bar(i / steps)}"))
            body.append((tag, "OK", f"{stage} done"))
        elif pick < 0.9 and facts.frame:
            body.append(("serial", "DEBUG", f"tx {hexdump(facts.frame)}"))
        else:
            body.append((r.choice(MODULES), "OK", f"self-test {r.randint(1, 64)}/64 passed"))
    return lines + body[:n - len(lines) - len(end)] + end
