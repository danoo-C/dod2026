"""The spectrum from the main screen (backend.md 7.4; tech-spec 5.2; plan step 8).

The main screen analyses the song it plays and sends 32 bands and a beat
flag ~30 times a second. The render loop asks for the spectrum of "now":

- with DOD_AUDIO_DELAY_MS, the one from that long ago – a Bluetooth speaker
  plays ~150-250 ms after the analyser hears it, so the lights wait for it
- stale after STALE seconds: it fades out over FADE seconds instead of
  freezing on the last picture (the main screen was closed, the tab hidden)

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


class AudioInput:
    def __init__(self, delay: float = 0.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.delay = delay
        self._clock = clock
        self._spectra: deque[tuple[float, tuple[float, ...], bool]] = deque()

    def push(self, bands: Sequence[float], beat: bool) -> None:
        """A spectrum from the main screen (the hub's on_spectrum)."""
        now = self._clock()
        self._spectra.append((now, tuple(float(b) for b in bands), bool(beat)))
        while self._spectra and self._spectra[0][0] < now - KEEP:
            self._spectra.popleft()

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
        at, bands, beat = latest
        age = target - at
        if age <= STALE:
            return Audio(bands=bands, beat=beat)
        fade = 1.0 - (age - STALE) / FADE
        if fade <= 0:
            return None
        return Audio(bands=tuple(b * fade for b in bands), beat=False)

    @property
    def beat(self) -> bool | None:
        """For the fake logs: the beat now, or None without a spectrum."""
        audio = self.current()
        return None if audio is None else audio.beat
