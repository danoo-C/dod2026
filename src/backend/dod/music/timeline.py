"""Each song's light show, worked out ahead: `<id>.show.png` next to the video,
shown under it on the main screen (backend.md 7.6).

The picture is the strip over the whole song: one column per frame (30 a
second), one band per LED, top = the first LED. It is made the way the show
itself is made:

1. the song's sound (ffmpeg), the spectrum the way the main screen's browser
   makes it: Web Audio's analyser (Blackman window, FFT_SIZE, smoothing, the
   byte range), then spectrum.ts (bands, LightLevels) and beat.ts (the kick)
2. those spectra through the backend's own AudioInput, the music effect and
   the output stage (the flash limit), at full brightness

So it shows what the strip will do, as close as the live show can be (the
live one also has the network's timing in it). The constants copied from the
frontend are checked against it by tests/test_timeline.py.

`./dod songs` makes it for every downloaded song that has none, or one from
an older show: `<id>.show.json` has VERSION, a hash of the code that makes
the show, so changing the show makes the pictures stale (they aren't served
until `./dod songs` makes them again – no internet needed for that).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
import zlib
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dod.engine.effects.base import Context
from dod.engine.effects.music import Music
from dod.engine.output import OutputStage
from dod.music.audio import AudioInput

FPS = 30
SAMPLE_RATE = 48000  # what Web Audio runs at on the notebook
HOP = SAMPLE_RATE // FPS

# --- copied from the frontend (tests/test_timeline.py checks them) --------------
# audioGraph.ts
FFT_SIZE = 2048
SMOOTHING = 0.5
# spectrum.ts
BANDS = 32
LOW_HZ = 40
HIGH_HZ = 16000
MIN_DB = -100
MAX_DB = -10
TILT_DB_PER_OCTAVE = 4.5
PIVOT_HZ = 1000
WINDOW_DB = 30
CURVE = 1.6
PEAK_FALL_DB = 0.1
PEAK_FLOOR_DB = 50
# beat.ts
LOW_BANDS = 5
WINDOW = 1.5
K = 1.5
MIN_FLUX_DB = 3
GAP = 0.34

# --- the picture -------------------------------------------------------------------
LED_PX = 4  # rows per LED
GAP_PX = 1  # dark rows between two LEDs
BACKGROUND = (10, 11, 22)

# the code that makes the show: a change to any of it makes the pictures stale
SOURCES = ("engine/effects/music.py", "engine/effects/base.py", "engine/output.py", "engine/color.py",
           "music/audio.py", "music/timeline.py")


def _version() -> str:
    package = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for name in SOURCES:
        h.update(name.encode())
        h.update((package / name).read_bytes().replace(b"\r\n", b"\n"))  # a Windows checkout hashes the same
    return h.hexdigest()[:16]


VERSION = _version()


# --- 1. the spectrum, the way the browser makes it -----------------------------------


def decode(video: Path) -> np.ndarray:
    """The song's sound, mono (the two channels' average, like Web Audio's analyser), float32."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).mean(axis=1)


def band_edges() -> list[tuple[int, int]]:
    """spectrum.ts bandEdges(): [first, last] bin of each band."""
    bin_hz = SAMPLE_RATE / FFT_SIZE
    bins = FFT_SIZE // 2
    edges, nxt = [], max(1, math.floor(LOW_HZ / bin_hz))
    for i in range(BANDS):
        top = LOW_HZ * (HIGH_HZ / LOW_HZ) ** ((i + 1) / BANDS)
        last = min(bins - 1, max(nxt, round(top / bin_hz) - 1))
        edges.append((nxt, last))
        nxt = min(bins - 1, last + 1)
    return edges


def raw_bands(samples: np.ndarray) -> np.ndarray:
    """Every 1/FPS s: the analyser's bytes (Web Audio), averaged into the bands
    (spectrum.ts toBands), 0-1. Frame i ends at sample i * HOP."""
    n = len(samples) // HOP + 1
    padded = np.concatenate([np.zeros(FFT_SIZE, dtype=np.float32), samples])
    window = np.blackman(FFT_SIZE + 1)[:FFT_SIZE]  # Web Audio's: periodic, a = 0.16
    edges = band_edges()
    bounds = np.array([a for a, _ in edges] + [edges[-1][1] + 1])  # the bands are contiguous
    widths = np.array([b - a + 1 for a, b in edges])
    smooth = np.zeros(FFT_SIZE // 2)
    out = np.empty((n, BANDS))
    chunk = 512
    for c in range(0, n, chunk):
        idx = np.arange(c, min(n, c + chunk))[:, None] * HOP + np.arange(FFT_SIZE)[None, :]
        mags = np.abs(np.fft.rfft(padded[idx] * window, axis=1))[:, :FFT_SIZE // 2] / FFT_SIZE
        for row, mag in enumerate(mags):
            smooth = SMOOTHING * smooth + (1 - SMOOTHING) * mag
            db = 20 * np.log10(np.maximum(smooth, 1e-20))
            byte = np.clip(np.floor(255 / (MAX_DB - MIN_DB) * (db - MIN_DB)), 0, 255)
            out[c + row] = np.add.reduceat(byte, bounds)[:BANDS] / widths / 255
    return out


class LightLevels:
    """spectrum.ts LightLevels: the bands as the lights get them."""

    def __init__(self) -> None:
        centres = LOW_HZ * (HIGH_HZ / LOW_HZ) ** ((np.arange(BANDS) + 0.5) / BANDS)
        self.tilt = TILT_DB_PER_OCTAVE * np.log2(centres / PIVOT_HZ)
        self.peak = float(PEAK_FLOOR_DB)

    def apply(self, bands: np.ndarray) -> list[float]:
        levels = np.where(bands > 0, bands * (MAX_DB - MIN_DB) + self.tilt, -np.inf)
        self.peak = max(PEAK_FLOOR_DB, float(levels.max()), self.peak - PEAK_FALL_DB)
        bottom = self.peak - WINDOW_DB
        return [float(v) for v in np.clip((levels - bottom) / WINDOW_DB, 0, 1) ** CURVE]


class BeatDetector:
    """beat.ts BeatDetector: the kick."""

    def __init__(self) -> None:
        self.history: deque[tuple[float, float]] = deque()
        self.previous: np.ndarray | None = None
        self.last = -math.inf

    def push(self, bands: np.ndarray, t: float) -> bool:
        low = bands[:LOW_BANDS]
        before = self.previous if self.previous is not None else low
        self.previous = low
        flux = float(np.maximum(0.0, low - before).mean()) * (MAX_DB - MIN_DB)
        while self.history and self.history[0][0] < t - WINDOW:
            self.history.popleft()
        n = len(self.history)
        mean = sum(f for _, f in self.history) / n if n else 0.0
        spread = math.sqrt(sum((f - mean) ** 2 for _, f in self.history) / n) if n > 1 else 0.0
        self.history.append((t, flux))
        if flux > MIN_FLUX_DB and flux > mean + K * spread and t - self.last >= GAP:
            self.last = t
            return True
        return False


def spectra(samples: np.ndarray) -> list[tuple[list[float], bool]]:
    """What the main screen would send, frame by frame: (bands for the lights, kick)."""
    lights, beats = LightLevels(), BeatDetector()
    return [(lights.apply(raw), beats.push(raw, i / FPS)) for i, raw in enumerate(raw_bands(samples))]


# --- 2. through the backend's own show ------------------------------------------------


@dataclass(frozen=True)
class Show:
    leds: list[tuple[tuple[int, int, int], ...]]  # per frame, per LED, 0-255 as a person sees it
    kicks: int
    snares: int
    hats: int
    drops: int


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def show(frames: Sequence[tuple[Sequence[float], bool]], led_count: int = 10) -> Show:
    """The strip, frame by frame, as the render loop would show it at full brightness."""
    clock = _Clock()
    audio = AudioInput(clock=clock)
    effect = Music()
    stage = OutputStage(brightness=1.0, power_limit_ma=1_000_000)
    leds = []
    for i, (bands, beat) in enumerate(frames):
        clock.t = 1000.0 + i / FPS
        audio.push(bands, beat)
        picture = effect.render(Context(led_count=led_count, t=i / FPS, audio=audio.current()))
        leds.append(stage.apply(picture, now=clock.t).preview.leds)
    last = audio.current()
    if last is None:
        return Show(leds, 0, 0, 0, 0)
    return Show(leds, last.count, last.snare_count, last.hat_count, last.drop_count)


# --- the picture ------------------------------------------------------------------------


def png(leds: Sequence[Sequence[tuple[int, int, int]]]) -> bytes:
    """The picture: one column per frame, LED_PX rows per LED with GAP_PX dark ones between."""
    width = max(1, len(leds))
    count = len(leds[0]) if leds else 1
    rows = []
    for j in range(count):
        line = b"\x00" + b"".join(bytes(frame[j]) for frame in leds) if leds else b"\x00" + bytes(BACKGROUND)
        rows += [line] * LED_PX
        if j < count - 1:
            rows += [b"\x00" + bytes(BACKGROUND) * width] * GAP_PX
    height = len(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


# --- in the cache --------------------------------------------------------------------------


def files(cache_dir: Path, song_id: str) -> tuple[Path, Path]:
    """`<id>.show.png` and `<id>.show.json` (VERSION and what was found), in the cache."""
    return cache_dir / f"{song_id}.show.png", cache_dir / f"{song_id}.show.json"


def current(cache_dir: Path, song_id: str) -> bool:
    """Whether the song has a picture made by this version of the show."""
    picture, meta = files(cache_dir, song_id)
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("version") == VERSION and picture.is_file()


def make(video: Path, cache_dir: Path, song_id: str) -> Show:
    """Works out the song's show and writes its picture; the .json last, so a
    half-written one never counts."""
    result = show(spectra(decode(video)))
    picture, meta = files(cache_dir, song_id)
    tmp = picture.with_name(picture.name + ".tmp")
    tmp.write_bytes(png(result.leds))
    tmp.replace(picture)
    meta.write_text(json.dumps({"version": VERSION, "fps": FPS, "frames": len(result.leds), "kicks": result.kicks,
                                "snares": result.snares, "hats": result.hats, "drops": result.drops}) + "\n",
                    encoding="utf-8")
    return result


def refresh(cache_dir: Path, songs: Sequence[tuple[str, Path]], say: Callable[[str], None] = print) -> list[str]:
    """Makes the picture of every (id, video) without a current one. Returns the ids that failed."""
    failed = []
    todo = [(i, v) for i, v in songs if not current(cache_dir, i)]
    for n, (song_id, video) in enumerate(todo, start=1):
        say(f"  show  {song_id}  ({n}/{len(todo)})")
        try:
            r = make(video, cache_dir, song_id)
            say(f"  done  {song_id}  {r.kicks} kicks, {r.snares} snares, {r.hats} hi-hats, {r.drops} drops")
        except Exception as e:  # ffmpeg, the disk
            failed.append(song_id)
            say(f"  FAIL  {song_id}  show: {type(e).__name__}: {e}")
    return failed
