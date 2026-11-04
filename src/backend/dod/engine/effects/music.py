"""The music mode's light show (backend.md 7.4; tech-spec 4.3): the spectrum
from the main screen on the strip, and 8 bars on the 8x8. Phones can't pick
it: it runs while a song plays.

Along the strip, the bands go from low (the first LED) to high, each LED as
bright as its share of the spectrum, the colours drifting slowly; a beat
lifts them a little. Without a spectrum (none yet, or it faded out) the
strip is dark and the 8x8 empty – the song's silence, not a frozen picture.
"""

from dod.engine.color import clamp01, hsv
from dod.engine.effects.base import Context, Effect
from dod.engine.matrix import bars, resample
from dod.engine.picture import Picture

HUE_SECONDS = 20.0  # once around the colour wheel
SPREAD = 0.6  # how much of the wheel the strip shows at once
FLOOR = 0.12  # a lit LED is never quite dark while music plays
BEAT_LIFT = 0.15  # added on a beat; small, so the beat never counts as a flash


class Music(Effect):
    id = "music"
    name = "Hudba"
    pickable = False

    def render(self, ctx: Context) -> Picture:
        n = ctx.led_count
        audio = ctx.audio
        if audio is None:
            return Picture(leds=[(0.0, 0.0, 0.0)] * n, matrix=bars([0.0] * 8), matrix_brightness=0.6)
        levels = resample(audio.bands, n)
        lift = BEAT_LIFT if audio.beat else 0.0
        base = ctx.t / HUE_SECONDS
        leds = [hsv(base + SPREAD * i / n, 1.0, clamp01(FLOOR + (1 - FLOOR) * v + lift)) for i, v in enumerate(levels)]
        return Picture(leds=leds, matrix=bars(resample(audio.bands, 8)), matrix_brightness=0.6)
