"""The music mode's light show (backend.md 7.5; tech-spec 4.3): a show on the
strip, and 8 bars on the 8x8. Phones can't pick it: it runs while a song
plays.

The kick drives it. Every kick:

- **pulses** the strip: an instant attack and a quick decay (PULSE_DECAY),
  stronger the more bass is in it, a little whiter at its peak
- **moves the colour on**, by COLOUR_PER_KICK times the song's bass: a
  bassy song jumps to a new colour on nearly every kick, a light one only
  shifts it. Between kicks the colour drifts, faster with more bass too.

Between kicks the strip falls back to a dim background in the opposite
colour of the palette, so every pulse stands out; in silence it is dark.
Treble (hi-hats, snares) throws white sparkles on top, one at a time.

Every SCENE_BEATS beats the pulse changes its shape, together with the
palette: the whole strip; from the centre out; alternating halves; comets
from alternating ends.

One pulse is one flash. The flash limit allows 3 a second, so above ~136 BPM
the pulses go half-time (every second kick), and the sparkles are one at a
time – a whole song never needs the limit (tested at 90-200 BPM).

The bands come from the main screen already shaped for the lights
(spectrum.ts, LightLevels), so a quiet moment is dark. What the show needs
from the past (the beats, the bass, the colour's sums) comes in Audio, kept
by dod.music.audio: the effect stays pure. Without a spectrum the strip is
dark and the 8x8 empty.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from dod.engine.color import RGB, WHITE, clamp01, hsv, mix, scale
from dod.engine.effects.base import Audio, Context, Effect
from dod.engine.matrix import bars, resample
from dod.engine.picture import Picture

SCENE_BEATS = 16  # beats per scene (and palette)

# colour palettes; one more than there are scenes, so scene and palette meet
# in a new combination each time
PALETTES: tuple[tuple[float, ...], ...] = (
    (0.0, 0.07, 0.12, 0.92),  # fire: red, orange, amber, pink
    (0.83, 0.5, 0.92, 0.58),  # neon: magenta, cyan, pink, blue
    (0.55, 0.62, 0.48, 0.75),  # ocean: blue, deep blue, teal, violet
    (0.25, 0.15, 0.33, 0.45),  # toxic: lime, yellow, green, aqua
    (0.0, 0.33, 0.66, 0.16),  # rainbow: red, green, blue, yellow
)

# --- the colour: how fast it changes --------------------------------------------
COLOUR_PER_KICK = 0.7  # palette turns a kick moves the colour, at full bass
COLOUR_DRIFT = 0.12  # palette turns a second between kicks, at full bass
OPPOSITE = 0.5  # the background's colour: this far round the palette from the kick's

# --- the kick's pulse -------------------------------------------------------------
PULSE_DECAY = 0.15  # seconds: the pulse falls to ~37 % in this long
PULSE_LENGTH = 0.5  # seconds: after this it is gone
PULSE_MIN = 0.45  # a kick with little bass still pulses this strong (of a full one)
PULSE_WHITE = 0.3  # whiter at the peak, for punch
HALF_TIME = 0.44  # kicks closer than this (> ~136 BPM): a pulse on every second one
SPREAD_SECONDS = 0.07  # the centre scene: from the centre to the ends

# --- between the kicks --------------------------------------------------------
BACKGROUND = 0.15  # the dim background at full loudness; it grows from 0, so silence is dark

# --- sparkles -----------------------------------------------------------------
SPARKLE_RATE = 20.0  # new sparkles a second, per LED slot
SPARKLE_DENSITY = 0.4  # share of LEDs sparkling at full treble
SPARKLE_MAX = 1  # at once: one bright glint; more would add flashes between the kicks
SPARKLE_LEVEL = 0.8
TREBLE_FROM = 22  # the bands from here up are the treble (~3 kHz and higher)

# --- comets ---------------------------------------------------------------------
COMET_SPEED = 30.0  # LEDs a second
COMET_TAIL = 3.0  # LEDs
COMET_FLOOD = 0.35  # the comets scene also pulses the whole strip this much

BASS_BANDS = 6  # the lowest bands: how hard this kick is


def _hash01(a: int, b: int) -> float:
    """A repeatable pseudo-random number 0-1 for the pair (a, b)."""
    x = (a * 0x9E3779B1 + b * 0x85EBCA77) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x ^= x >> 12
    x = (x * 0x297A2D39) & 0xFFFFFFFF
    x ^= x >> 15
    return x / 2**32


def _palette(hues: Sequence[float], x: float) -> RGB:
    """A colour from the palette at position x (wraps): its hues, blended."""
    k = len(hues)
    pos = (x % 1.0) * k
    i = int(pos) % k
    return mix(hsv(hues[i]), hsv(hues[(i + 1) % k]), pos - int(pos))


def _add(a: RGB, b: RGB) -> RGB:
    return (min(1.0, a[0] + b[0]), min(1.0, a[1] + b[1]), min(1.0, a[2] + b[2]))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def colour_position(audio: Audio) -> float:
    """Where on the palette the kick's colour is now (wraps at 1)."""
    return COLOUR_PER_KICK * audio.kick_sum + COLOUR_DRIFT * audio.bass_travel


def pulse(audio: Audio) -> tuple[float, float]:
    """(strength 0-1, age in seconds) of the kick's pulse showing now; strength 0 between kicks."""
    beats = audio.beats
    if not beats:
        return 0.0, math.inf
    age = beats[0]
    if len(beats) > 1 and beats[1] - beats[0] < HALF_TIME and audio.count % 2:
        age = beats[1]  # a fast song: this kick is skipped, the one before goes on fading
    if age >= PULSE_LENGTH:
        return 0.0, age
    hard = clamp01(_mean(audio.bands[:BASS_BANDS]) * 1.3)
    return math.exp(-age / PULSE_DECAY) * (PULSE_MIN + (1 - PULSE_MIN) * hard), age


# --- the scenes: where the pulse lights up ---------------------------------------
# (led count, audio, the kick's colour, strength, age) -> the pulse layer

Scene = Callable[[int, Audio, RGB, float, float], list[RGB]]
DARK: RGB = (0.0, 0.0, 0.0)


def flood(n: int, audio: Audio, colour: RGB, strength: float, age: float) -> list[RGB]:
    return [scale(colour, strength)] * n


def centre(n: int, audio: Audio, colour: RGB, strength: float, age: float) -> list[RGB]:
    middle = (n - 1) / 2
    reach = 0.5 + middle * min(1.0, age / SPREAD_SECONDS)  # the middle LEDs at once, then out to the ends
    return [scale(colour, strength) if abs(i - middle) <= reach else DARK for i in range(n)]


def halves(n: int, audio: Audio, colour: RGB, strength: float, age: float) -> list[RGB]:
    left = audio.count % 2 == 0
    return [scale(colour, strength if (i < n / 2) == left else strength * 0.15) for i in range(n)]


def comets(n: int, audio: Audio, colour: RGB, strength: float, age: float) -> list[RGB]:
    out = [scale(colour, strength * COMET_FLOOD)] * n
    for k, beat_age in enumerate(audio.beats):
        head = beat_age * COMET_SPEED
        if head - COMET_TAIL > n:
            continue  # gone past the end
        number = audio.count - 1 - k  # which beat launched it: even from the start, odd from the end
        for i in range(n):
            pos = i if number % 2 == 0 else n - 1 - i
            behind = head - pos
            if 0 <= behind <= COMET_TAIL:
                out[i] = _add(out[i], scale(colour, (1 - behind / COMET_TAIL) ** 1.5))
    return out


SCENES: tuple[Scene, ...] = (flood, centre, halves, comets)


# --- the layers around the pulse --------------------------------------------------


def background(n: int, audio: Audio, pal: Sequence[float], position: float) -> list[RGB]:
    level = BACKGROUND * math.sqrt(_mean(audio.bands))  # soon visible, never in silence
    return [scale(_palette(pal, position + OPPOSITE + 0.3 * i / n), level) for i in range(n)]


def sparkles(n: int, t: float, audio: Audio, density: float = SPARKLE_DENSITY) -> list[RGB]:
    level = _mean(audio.bands[TREBLE_FROM:])
    slot = int(t * SPARKLE_RATE)
    fade = 1 - (t * SPARKLE_RATE - slot)  # each sparkle dies out within its slot
    chances = sorted((_hash01(slot, i), i) for i in range(n))
    lit = [i for r, i in chances[:SPARKLE_MAX] if r < level * density]
    out = [DARK] * n
    for i in lit:
        out[i] = scale(WHITE, SPARKLE_LEVEL * fade)
    return out


class Music(Effect):
    id = "music"
    name = "Hudba"
    pickable = False

    def render(self, ctx: Context) -> Picture:
        n = ctx.led_count
        audio = ctx.audio
        if audio is None:
            return Picture(leds=[DARK] * n, matrix=bars([0.0] * 8), matrix_brightness=0.6)
        part = audio.count // SCENE_BEATS
        scene = SCENES[part % len(SCENES)]
        pal = PALETTES[part % len(PALETTES)]
        position = colour_position(audio)
        strength, age = pulse(audio)
        colour = mix(_palette(pal, position), WHITE, PULSE_WHITE * strength)
        layers = (background(n, audio, pal, position), scene(n, audio, colour, strength, age),
                  sparkles(n, ctx.t, audio))
        leds = [_add(_add(a, b), c) for a, b, c in zip(*layers)]
        return Picture(leds=leds, matrix=bars(resample(audio.bands, 8)), matrix_brightness=0.6)
