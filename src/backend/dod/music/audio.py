"""The spectrum from the main screen (backend.md 7.4; tech-spec 5.2; plan step 8).

The main screen analyses the song it plays and sends 32 bands and a beat
flag ~30 times a second. The render loop asks for the spectrum of "now":

- with DOD_AUDIO_DELAY_MS, the one from that long ago – a Bluetooth speaker
  plays ~150-250 ms after the analyser hears it, so the lights wait for it
- stale after STALE seconds: it fades out over FADE seconds instead of
  freezing on the last picture (the main screen was closed, the tab hidden)

It also keeps what the light show needs from the past, since effects are
pure: when the last few beats were, how many beats there have been (the
scenes change every 16), `travel` (the loudness summed over time), and the
bass: how much of it the song has lately, summed over time, and summed at
each beat – the colours change faster in a bassy song. All of it on the
delayed timeline, so it stays in step with the bands.

All times are the render loop's monotonic clock.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Sequence

from dod.engine.effects.base import Audio

STALE = 0.2  # seconds without a new spectrum before it starts to fade
FADE = 0.3  # seconds from full to nothing after that
KEEP = 3.0  # seconds of spectra kept for the delay (the delay is at most 2 s)
BEATS_KEPT = 4  # beats the light show can see (its comets)
MAX_STEP = 0.1  # seconds: a gap in the spectra counts as at most this much travel
BASS_BANDS = 6  # the lowest bands (~40-160 Hz): the kick drum and the bass
BASS_SECONDS = 1.5  # how quickly `bass` follows the song


class AudioInput:
    def __init__(self, delay: float = 0.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.delay = delay
        self._clock = clock
        # (time, bands, beat, then the running values of the Audio fields below)
        self._spectra: deque[tuple[float, tuple[float, ...], bool, int, float, float, float, float]] = deque()
        self._beat_times: deque[float] = deque()
        self._count = 0
        self._travel = 0.0
        self._bass = 0.0
        self._bass_travel = 0.0
        self._kick_sum = 0.0

    def push(self, bands: Sequence[float], beat: bool) -> None:
        """A spectrum from the main screen (the hub's on_spectrum)."""
        now = self._clock()
        values = tuple(float(b) for b in bands)
        low = values[:BASS_BANDS]
        bass_now = sum(low) / len(low) if low else 0.0
        if self._spectra:
            step = min(MAX_STEP, max(0.0, now - self._spectra[-1][0]))
            self._travel += step * (sum(values) / len(values) if values else 0.0)
            self._bass += (bass_now - self._bass) * min(1.0, step / BASS_SECONDS)
            self._bass_travel += step * self._bass
        if beat:
            self._count += 1
            self._beat_times.append(now)
            self._kick_sum += self._bass
        self._spectra.append((now, values, bool(beat), self._count, self._travel,
                              self._bass, self._bass_travel, self._kick_sum))
        while self._spectra and self._spectra[0][0] < now - KEEP:
            self._spectra.popleft()
        while len(self._beat_times) > BEATS_KEPT + 64 or (self._beat_times and self._beat_times[0] < now - KEEP):
            self._beat_times.popleft()

    def current(self, now: float | None = None) -> Audio | None:
        """The spectrum to show at `now`: delayed, faded when stale; None when silent."""
        now = self._clock() if now is None else now
        target = now - self.delay
        latest = None
        for entry in reversed(self._spectra):
            if entry[0] <= target:
                latest = entry
                break
        if latest is None:
            return None
        at, bands, beat, count, travel, bass, bass_travel, kick_sum = latest
        beats = tuple(target - t for t in reversed(self._beat_times) if t <= target)[:BEATS_KEPT]
        past = {"beats": beats, "count": count, "travel": travel, "bass": bass,
                "bass_travel": bass_travel, "kick_sum": kick_sum}
        age = target - at
        if age <= STALE:
            return Audio(bands=bands, beat=beat, **past)
        fade = 1.0 - (age - STALE) / FADE
        if fade <= 0:
            return None
        return Audio(bands=tuple(b * fade for b in bands), beat=False, **past)

    @property
    def beat(self) -> bool | None:
        """For the fake logs: the beat now, or None without a spectrum."""
        audio = self.current()
        return None if audio is None else audio.beat
