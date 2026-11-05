"""The spectrum from the main screen (backend.md 7.4; tech-spec 5.2; plan step 8).

The main screen analyses the song it plays and sends 32 bands and a kick
flag ~30 times a second. The render loop asks for the spectrum of "now":

- with DOD_AUDIO_DELAY_MS, the one from that long ago – a Bluetooth speaker
  plays ~150-250 ms after the analyser hears it, so the lights wait for it
- stale after STALE seconds: it fades out over FADE seconds instead of
  freezing on the last picture (the main screen was closed, the tab hidden)

Effects are pure, so this also keeps everything the light show needs from
the past, on the delayed timeline so it stays in step with the bands:

- the events: kicks (from the main screen), snares and hi-hats (onsets
  found here: a sudden rise of the mid or the top bands, compared with how
  much those bands usually jump), and drops (a kick with the bass back in a
  calm part) – when the last few were, and how many there have been
- the song's shape: `level` (loudness, smoothed), `calm` (no kicks lately,
  or the bass gone: a breakdown), `build` (a calm part getting louder, or a
  snare roll: towards a drop)
- running sums the colours move with: `travel`, `bass`, `bass_travel`, `kick_sum`
- `held`: the bands, falling no faster than BAR_FALL – the 8x8's bars

All times are the render loop's monotonic clock.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from dod.engine.effects.base import Audio

STALE = 0.2  # seconds without a new spectrum before it starts to fade
FADE = 0.3  # seconds from full to nothing after that
KEEP = 3.0  # seconds of spectra kept for the delay (the delay is at most 2 s)
MAX_STEP = 0.1  # seconds: a gap in the spectra counts as at most this much time

BEATS_KEPT = 4  # kicks the light show can see (its comets)
SNARES_KEPT = 2
HATS_KEPT = 4

BASS_BANDS = 6  # the lowest bands (~40-160 Hz): the kick drum and the bass
BASS_SECONDS = 1.5  # how quickly `bass` follows the song
LEVEL_SECONDS = 0.35  # how quickly `level` follows the loudness
BAR_FALL = 0.8  # `held`: a band falls at most this much a second (the 8x8's bars; under the flash limit)

# --- snares and hi-hats: onsets on the bands as the lights get them ------------
SNARE_BANDS = (12, 23)  # ~400 Hz-3 kHz: snares, claps, the voice's attacks
HAT_BANDS = (25, 32)  # ~5 kHz and up: hi-hats, shakers, cymbals


@dataclass(frozen=True)
class Onsets:
    """How an onset is found in a group of bands."""

    bands: tuple[int, int]  # [first, last) band
    minimum: float  # the rise (average per band, on the 0-1 scale) must be at least this
    k: float  # ... and this many spreads above the usual rise
    gap: float  # seconds, at least, between two


SNARE = Onsets(SNARE_BANDS, minimum=0.06, k=2.0, gap=0.15)
HAT = Onsets(HAT_BANDS, minimum=0.06, k=1.5, gap=0.09)
ONSET_WINDOW = 1.5  # seconds of rises the usual one is measured on

# --- the song's shape -------------------------------------------------------------
CALM_AFTER = 2.0  # seconds without a kick: calm (a quiet intro, a pause in the beat)
CALM_BASS = 0.5  # ... or the bass under this share of the song's loudest so far (a breakdown)
CALM_SECONDS = 0.6  # how quickly `calm` follows
SONG_GAP = 1.0  # seconds without spectra: a new song (or a pause), the loudest bass starts over
SLOW_SECONDS = 4.0  # the loudness, smoothed this slowly: is it rising?
RISING = 0.015  # `level` this far above the slow loudness: rising
BUILD_SECONDS = 6.0  # a calm part that keeps rising is a full build after this long
BUILD_FALL = 0.5  # ... and lets go at this share of that speed when it stops
BUILD_SNARES = 2.5  # snares a second that count as a build (a snare roll)
DROP_BASS = 0.6  # a drop: a kick in a calm part, with the bass back to this share of the loudest
DROP_CALM = 4.0  # ... after at least this many seconds of it
DROP_HOLD = 4.0  # seconds after a drop that can't be calm
DROP_GAP = 8.0  # seconds, at least, between two drops


class _Onset:
    """Finds the onsets of one group of bands (spectral flux, like the kick)."""

    def __init__(self, spec: Onsets) -> None:
        self.spec = spec
        self._previous: tuple[float, ...] | None = None
        self._rises: deque[tuple[float, float]] = deque()
        self._last = -math.inf

    def push(self, bands: Sequence[float], now: float) -> bool:
        first, last = self.spec.bands
        group = tuple(bands[first:last])
        before = self._previous if self._previous is not None else group
        self._previous = group
        rise = sum(max(0.0, a - b) for a, b in zip(group, before)) / max(1, len(group))
        while self._rises and self._rises[0][0] < now - ONSET_WINDOW:
            self._rises.popleft()
        n = len(self._rises)
        mean = sum(r for _, r in self._rises) / n if n else 0.0
        spread = math.sqrt(sum((r - mean) ** 2 for _, r in self._rises) / n) if n > 1 else 0.0
        self._rises.append((now, rise))
        if rise > self.spec.minimum and rise > mean + self.spec.k * spread and now - self._last >= self.spec.gap:
            self._last = now
            return True
        return False


@dataclass(frozen=True)
class _Snapshot:
    """The running values at one spectrum, for the delayed timeline."""

    at: float
    bands: tuple[float, ...]
    held: tuple[float, ...]
    beat: bool
    count: int
    snare_count: int
    hat_count: int
    drop_count: int
    travel: float
    bass: float
    bass_travel: float
    kick_sum: float
    level: float
    calm: float
    build: float


class AudioInput:
    def __init__(self, delay: float = 0.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.delay = delay
        self._clock = clock
        self._spectra: deque[_Snapshot] = deque()
        self._events: dict[str, deque[float]] = {k: deque() for k in ("beat", "snare", "hat", "drop")}
        self._snare = _Onset(SNARE)
        self._hat = _Onset(HAT)
        self._counts = {k: 0 for k in self._events}
        self._travel = self._bass = self._bass_travel = self._kick_sum = 0.0
        self._level = self._calm = self._build = 0.0
        self._last_beat = self._last_drop = -math.inf
        self._slow = 0.0  # the loudness, smoothed over SLOW_SECONDS
        self._bass_ref = 0.0  # the song's loudest `bass` so far
        self._calm_since = math.inf  # when the calm part began
        self._held: tuple[float, ...] = ()

    def push(self, bands: Sequence[float], beat: bool) -> None:
        """A spectrum from the main screen (the hub's on_spectrum)."""
        now = self._clock()
        values = tuple(float(b) for b in bands)
        loud = sum(values) / len(values) if values else 0.0
        low = values[:BASS_BANDS]
        bass_now = sum(low) / len(low) if low else 0.0
        gap = now - self._spectra[-1].at if self._spectra else math.inf
        if gap > SONG_GAP:  # a new song (or a pause): its bass starts over
            self._bass = self._bass_ref = 0.0
            self._held = ()
        step = min(MAX_STEP, max(0.0, gap)) if self._spectra else 0.0

        self._travel += step * loud
        self._bass += (bass_now - self._bass) * min(1.0, step / BASS_SECONDS)
        self._bass_travel += step * self._bass
        self._bass_ref = max(self._bass_ref, self._bass)
        self._level += (loud - self._level) * min(1.0, step / LEVEL_SECONDS)
        self._slow += (loud - self._slow) * min(1.0, step / SLOW_SECONDS)
        if len(self._held) != len(values):
            self._held = values
        self._held = tuple(max(v, h - BAR_FALL * step) for v, h in zip(values, self._held))

        events = {"beat": bool(beat), "snare": self._snare.push(values, now), "hat": self._hat.push(values, now),
                  "drop": False}
        if beat:
            if (self._calm > 0.5 and now - self._calm_since >= DROP_CALM and bass_now >= DROP_BASS * self._bass_ref and bass_now > 0
                    and now - self._last_drop >= DROP_GAP):
                events["drop"] = True
                self._last_drop = now
                self._calm = self._build = 0.0
            self._last_beat = now
            self._kick_sum += self._bass
        for kind, happened in events.items():
            if happened:
                self._counts[kind] += 1
                self._events[kind].append(now)

        # calm: no kicks lately, or the bass gone (a breakdown); not right after a drop
        calm_now = (now - self._last_drop >= DROP_HOLD
                    and (now - self._last_beat >= CALM_AFTER or self._bass < CALM_BASS * self._bass_ref))
        self._calm += (float(calm_now) - self._calm) * min(1.0, step / CALM_SECONDS)
        if not calm_now:
            self._calm_since = math.inf
        elif self._calm_since == math.inf:
            self._calm_since = now
        # build: a calm part getting louder, or a snare roll
        snares = sum(1 for t in self._events["snare"] if t > now - 2.0) / 2.0
        if calm_now and (self._level > self._slow + RISING or snares >= BUILD_SNARES):
            self._build = min(1.0, self._build + step / BUILD_SECONDS)
        elif not calm_now:
            self._build = 0.0
        else:
            self._build = max(0.0, self._build - step * BUILD_FALL / BUILD_SECONDS)

        self._spectra.append(_Snapshot(
            at=now, bands=values, held=self._held, beat=bool(beat), count=self._counts["beat"],
            snare_count=self._counts["snare"], hat_count=self._counts["hat"], drop_count=self._counts["drop"], travel=self._travel, bass=self._bass,
            bass_travel=self._bass_travel, kick_sum=self._kick_sum, level=self._level, calm=self._calm,
            build=self._build))
        while self._spectra and self._spectra[0].at < now - KEEP:
            self._spectra.popleft()
        for times in self._events.values():
            while len(times) > 64 or (times and times[0] < now - KEEP):
                times.popleft()

    def _ages(self, kind: str, target: float, keep: int) -> tuple[float, ...]:
        return tuple(target - t for t in reversed(self._events[kind]) if t <= target)[:keep]

    def current(self, now: float | None = None) -> Audio | None:
        """The spectrum to show at `now`: delayed, faded when stale; None when silent."""
        now = self._clock() if now is None else now
        target = now - self.delay
        s = next((entry for entry in reversed(self._spectra) if entry.at <= target), None)
        if s is None:
            return None
        drops = self._ages("drop", target, 1)
        audio = Audio(
            bands=s.bands, held=s.held, beat=s.beat, beats=self._ages("beat", target, BEATS_KEPT), count=s.count,
            travel=s.travel, bass=s.bass, bass_travel=s.bass_travel, kick_sum=s.kick_sum,
            snares=self._ages("snare", target, SNARES_KEPT), snare_count=s.snare_count,
            hats=self._ages("hat", target, HATS_KEPT), hat_count=s.hat_count,
            drop=drops[0] if drops else math.inf, drop_count=s.drop_count,
            level=s.level, calm=s.calm, build=s.build)
        age = target - s.at
        if age <= STALE:
            return audio
        fade = 1.0 - (age - STALE) / FADE
        if fade <= 0:
            return None
        return replace(audio, bands=tuple(b * fade for b in s.bands), held=tuple(b * fade for b in s.held),
                       beat=False, level=s.level * fade)

    @property
    def beat(self) -> bool | None:
        """For the fake logs: the beat now, or None without a spectrum."""
        audio = self.current()
        return None if audio is None else audio.beat
