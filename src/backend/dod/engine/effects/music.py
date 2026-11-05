"""The music mode's light show (backend.md 7.5; tech-spec 4.3): a show on the
strip, and 8 bars on the 8x8. Phones can't pick it: it runs while a song
plays.

The 8x8 shows 8 bars of the spectrum that jump up at once and fall slowly.

The strip is built from layers, each driven by something in the song:

- **base**: a moving, many-coloured picture. It follows the spectrum (bass in
  the middle, treble at the ends), scrolls faster when the song is louder,
  and its colours move on with every kick. Three looks, one per scene.
- **kick**: a hit in the kick's colour, in the scene's shape: a burst from
  the centre, the whole strip, alternating halves, a comet from alternate
  ends, or three scattered spots.
- **snare**: the outer LEDs of one side flash the palette's opposite colour,
  the other side on the next snare.
- **hi-hat**: a glint on a random LED.
- **calm** (no kicks for 2 s, or the bass gone: a breakdown): the base turns into slow,
  dimmer waves of two colours.
- **build** (a calm part getting louder or busier): a riser fills the strip
  from both ends towards the middle, whiter as it grows.
- **drop** (a kick with the bass back, in a calm part): a full white hit, and the
  next scene and palette at once.

Every SCENE_BEATS kicks (and at a drop) the scene changes: kick shape, base
look and palette, in different cycles, so the combinations keep changing.

**The flash limit** (output.py: 0.2 steps of the strip's average brightness,
6 a second) is planned for, not hit: the base is scaled to a slowly moving
brightness, whatever its colours and pattern do, and snares and glints are
small. Only kicks and drops change the average brightness by a step: each
one is one flash, and the main screen sends at most ~2.9 kicks a second. In a
fast song (kicks closer than HALF_TIME) every second kick is a small hit,
which changes the colours and the shape but not the brightness. Whole songs
pass the limit untouched (tests/test_music_audio.py, with simulated songs;
and the 10 songs of the stand, checked offline).

The bands come from the main screen already shaped for the lights
(spectrum.ts, LightLevels), so a quiet moment is dark. What the show needs
from the past comes in Audio, kept by dod.music.audio: the effect stays pure.
Without a spectrum the strip is dark and the 8x8 empty.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from dod.engine.color import RGB, WHITE, clamp01, hsv, luminance, mix, scale
from dod.engine.effects.base import Audio, Context, Effect
from dod.engine.matrix import bars, resample
from dod.engine.picture import Picture

SCENE_BEATS = 32  # kicks per scene: ~8 bars, a phrase of the song

# colour palettes, hues 0-1; their count shares no factor with the scenes', so
# each scene meets each palette in turn
PALETTES: tuple[tuple[float, ...], ...] = (
    (0.0, 0.06, 0.12, 0.93),  # fire: red, orange, amber, pink
    (0.83, 0.5, 0.92, 0.58),  # neon: magenta, cyan, pink, blue
    (0.55, 0.65, 0.47, 0.75),  # ocean: blue, deep blue, teal, violet
    (0.25, 0.14, 0.33, 0.45),  # toxic: lime, yellow, green, aqua
    (0.95, 0.07, 0.78, 0.13),  # sunset: pink, orange, purple, gold
    (0.0, 0.33, 0.66, 0.16),  # rainbow: red, green, blue, yellow
    (0.7, 0.0, 0.62, 0.9),  # club: violet, red, blue, magenta
)

# --- the colours: how fast they move -------------------------------------------
COLOUR_PER_KICK = 0.17  # palette turns a kick moves the colours, at full bass
COLOUR_DRIFT = 0.05  # palette turns a second between kicks, at full bass
OPPOSITE = 0.5  # the accent colour: this far round the palette from the kick's

# --- base -------------------------------------------------------------------------
BASE_LEVEL = 0.3  # the base's average brightness at full loudness
LEVEL_FULL = 0.4  # the loudness (mean of the bands) that counts as full
BASE_FLOOR = 0.25  # an LED of the base never goes darker than this share of its colour
BASE_GAIN = 4.0  # the base may be scaled up at most this much to reach its brightness
SCROLL = 1.2  # the base moves this many turns per unit of travel (louder: faster)
CALM_DIM = 0.35  # calm: the base this much dimmer

# --- kick -------------------------------------------------------------------------
HIT_LEVEL = 0.6  # brightness of a full hit's colour (its luminance; dark colours can't reach it)
HIT_DECAY = 0.13  # seconds: the hit falls to ~37 % in this long
HIT_LENGTH = 0.45  # seconds: after this it is gone
HIT_MIN = 0.5  # a kick with little bass still hits this strong (of a full one)
HIT_WHITE = 0.35  # whiter at the peak, for punch
HALF_TIME = 0.44  # kicks closer than this (> ~136 BPM): every second one is a small hit
SMALL_HIT = 0.25  # ... this strong
SPREAD_SECONDS = 0.08  # the burst: from the centre to the ends
COMET_SPEED = 40.0  # LEDs a second
COMET_TAIL = 3.0  # LEDs
COMET_FLOOD = 0.3  # the comet scene also lights the whole strip this much
SPOTS = 3  # the scatter scene: spots per kick

# --- drop -------------------------------------------------------------------------
DROP_DECAY = 0.3  # seconds: a drop's hit fades slower than a kick's
DROP_LENGTH = 0.9

# --- snare ------------------------------------------------------------------------
SNARE_LEVEL = 0.35  # brightness of the snare's colour (its luminance)
SNARE_DECAY = 0.07
SNARE_LENGTH = 0.25
SNARE_WIDTH = 3  # LEDs at the end of a side

# --- hi-hats -----------------------------------------------------------------------
GLINT_LEVEL = 0.45  # brightness of a glint
GLINT_LENGTH = 0.15  # seconds
GLINT_WHITE = 0.6  # a glint is the palette's colour this much whitened

# --- build --------------------------------------------------------------------------
RISER_LEVEL = 0.4  # brightness of the riser's LEDs at the end of a build
RISER_WHITE = 0.45  # ... whitened this much
RISER_SPEED = (2.0, 8.0)  # its stripes: turns per unit of travel, at the start and the end of a build

BASS_BANDS = 6  # the lowest bands: how hard this kick is
DARK: RGB = (0.0, 0.0, 0.0)


# --- helpers ------------------------------------------------------------------------


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


def _bright(c: RGB, level: float) -> RGB:
    """The colour c at the luminance `level`, or as close as it gets (a deep blue can't be bright)."""
    lum, top = luminance(c), max(c)
    if lum <= 0 or top <= 0:
        return DARK
    return scale(c, min(level / lum, 1 / top))


def _level(leds: Sequence[RGB]) -> float:
    return _mean([luminance(c) for c in leds])


def _over(below: list[RGB], above: Sequence[RGB], amount: Sequence[float]) -> list[RGB]:
    """`above` laid over `below`, per LED by `amount` 0-1."""
    return [mix(b, a, clamp01(f)) if f > 0 else b for b, a, f in zip(below, above, amount)]


def colour_position(audio: Audio) -> float:
    """Where on the palette the kick's colour is now (wraps at 1)."""
    return COLOUR_PER_KICK * audio.kick_sum + COLOUR_DRIFT * audio.bass_travel


def scene_number(audio: Audio) -> int:
    """Which scene: the next every SCENE_BEATS kicks, and at every drop."""
    return audio.count // SCENE_BEATS + audio.drop_count


# --- base: three looks --------------------------------------------------------------
# (led count, audio, palette, colour position) -> colours, any brightness;
# base() scales them to the right one

Look = Callable[[int, Audio, Sequence[float], float], list[RGB]]


def _band_at(bands: Sequence[float], x: float) -> float:
    """The spectrum at x, 0 (bass) to 1 (treble): the average of a few bands around it."""
    if not bands:
        return 0.0
    k = len(bands)
    centre = round(x * (k - 1))
    return _mean(bands[max(0, centre - 2):centre + 3])


def spectrum(n: int, audio: Audio, pal: Sequence[float], pos: float) -> list[RGB]:
    """The bass in the middle, the treble at the ends; colours spread out from the middle."""
    middle = (n - 1) / 2
    out = []
    for i in range(n):
        d = abs(i - middle) / middle if middle else 0.0
        weight = BASE_FLOOR + (1 - BASE_FLOOR) * _band_at(audio.bands, d)
        out.append(scale(_palette(pal, pos + 0.35 * d - 0.1 * audio.travel * SCROLL), weight))
    return out


def gradient(n: int, audio: Audio, pal: Sequence[float], pos: float) -> list[RGB]:
    """The palette along the strip, scrolling, with a brighter wave running through it."""
    phase = audio.travel * SCROLL
    out = []
    for i in range(n):
        x = i / n
        weight = BASE_FLOOR + (1 - BASE_FLOOR) * (0.5 + 0.5 * math.sin(2 * math.pi * (1.5 * x - phase)))
        out.append(scale(_palette(pal, pos + 0.6 * x - 0.3 * phase), weight))
    return out


def waves(n: int, audio: Audio, pal: Sequence[float], pos: float) -> list[RGB]:
    """Two colours in waves running against each other (also the calm look)."""
    phase = audio.travel * SCROLL
    a, b = _palette(pal, pos), _palette(pal, pos + OPPOSITE)
    out = []
    for i in range(n):
        x = i / max(1, n - 1)
        wa = 0.5 + 0.5 * math.sin(2 * math.pi * (x - phase))
        wb = 0.5 + 0.5 * math.sin(2 * math.pi * (0.7 * x + 1.3 * phase + 0.25))
        out.append(_add(scale(a, BASE_FLOOR + wa), scale(b, 0.8 * wb)))
    return out


LOOKS: tuple[Look, ...] = (spectrum, gradient, waves)


def base_level(audio: Audio) -> float:
    """How bright the base is on average: with the loudness, dimmer when calm."""
    return BASE_LEVEL * min(1.0, audio.level / LEVEL_FULL) * (1 - CALM_DIM * audio.calm)


def base(n: int, audio: Audio, pal: Sequence[float], pos: float, look: Look) -> list[RGB]:
    """The look, scaled so its average brightness is base_level(): its pattern and
    colours can change at any speed, the strip's brightness only with the loudness."""
    leds = (waves if audio.calm > 0.5 else look)(n, audio, pal, pos)
    have = _level(leds)
    top = max((max(c) for c in leds), default=0.0)
    if have <= 0 or top <= 0:
        return [DARK] * n
    return [scale(c, min(base_level(audio) / have, 1 / top, BASE_GAIN)) for c in leds]


# --- kick: the hit and its shapes ---------------------------------------------------


def hit(audio: Audio) -> tuple[float, float]:
    """(strength 0-1, age in seconds) of the hit showing now; strength 0 between kicks.
    A drop hits at full strength and fades slower."""
    beats = audio.beats
    strength, age = 0.0, math.inf
    if beats and beats[0] < HIT_LENGTH:
        age = beats[0]
        hard = clamp01(_mean(audio.bands[:BASS_BANDS]) * 1.3)
        strength = math.exp(-age / HIT_DECAY) * (HIT_MIN + (1 - HIT_MIN) * hard)
        if len(beats) > 1 and beats[1] - beats[0] < HALF_TIME and audio.count % 2:
            strength *= SMALL_HIT  # a fast song: every second kick only changes colour and shape
    if audio.drop < DROP_LENGTH:
        strength = max(strength, math.exp(-audio.drop / DROP_DECAY))
        age = min(age, audio.drop)
    return strength, age


# (led count, audio, age of the hit) -> how much of the hit each LED shows, 0-1

Shape = Callable[[int, Audio, float], list[float]]


def burst(n: int, audio: Audio, age: float) -> list[float]:
    """From the centre out to the ends."""
    middle = (n - 1) / 2
    reach = 0.5 + middle * min(1.0, age / SPREAD_SECONDS)
    return [1.0 if abs(i - middle) <= reach else 0.0 for i in range(n)]


def flood(n: int, audio: Audio, age: float) -> list[float]:
    """The whole strip."""
    return [1.0] * n


def halves(n: int, audio: Audio, age: float) -> list[float]:
    """One half, the other on the next kick."""
    left = audio.count % 2 == 0
    return [1.0 if (i < n / 2) == left else 0.1 for i in range(n)]


def comet(n: int, audio: Audio, age: float) -> list[float]:
    """A comet from one end, from the other on the next kick, over a dim flood."""
    head = age * COMET_SPEED
    from_end = audio.count % 2 == 1
    out = []
    for i in range(n):
        behind = head - (n - 1 - i if from_end else i)
        tail = (1 - behind / COMET_TAIL) ** 1.5 if 0 <= behind <= COMET_TAIL else 0.0
        out.append(max(COMET_FLOOD, tail))
    return out


def scatter(n: int, audio: Audio, age: float) -> list[float]:
    """A few spots, somewhere else on every kick."""
    out = [0.0] * n
    for k in range(SPOTS):
        i = int(_hash01(audio.count, k) * n) % n
        out[i] = 1.0
        for j in (i - 1, i + 1):
            if 0 <= j < n:
                out[j] = max(out[j], 0.4)
    return out


SHAPES: tuple[Shape, ...] = (burst, flood, halves, comet, scatter)


def kick(n: int, audio: Audio, pal: Sequence[float], pos: float, shape: Shape) -> tuple[list[RGB], list[float]]:
    """The hit: its colours, and how much each LED shows it."""
    strength, age = hit(audio)
    if strength <= 0:
        return [DARK] * n, [0.0] * n
    drop = audio.drop < DROP_LENGTH and audio.drop <= age
    colour = mix(_palette(pal, pos), WHITE, 1.0 if drop and age < 0.1 else HIT_WHITE * strength)
    lit = flood(n, audio, age) if drop else shape(n, audio, age)
    return [_bright(colour, HIT_LEVEL)] * n, [strength * f for f in lit]


# --- snares, hi-hats, the riser -------------------------------------------------------


def snare(n: int, audio: Audio, pal: Sequence[float], pos: float) -> tuple[list[RGB], list[float]]:
    """The outer LEDs of one side in the opposite colour; the other side on the next snare."""
    if not audio.snares or audio.snares[0] >= SNARE_LENGTH:
        return [DARK] * n, [0.0] * n
    f = math.exp(-audio.snares[0] / SNARE_DECAY)
    right = audio.snare_count % 2 == 0
    width = min(SNARE_WIDTH, n // 2)
    colour = _bright(_palette(pal, pos + OPPOSITE), SNARE_LEVEL)
    amount = [f if (i >= n - width if right else i < width) else 0.0 for i in range(n)]
    return [colour] * n, amount


def glints(n: int, audio: Audio, pal: Sequence[float], pos: float) -> tuple[list[RGB], list[float]]:
    """A glint on a random LED for each hi-hat."""
    amount = [0.0] * n
    for k, age in enumerate(audio.hats):
        if age < GLINT_LENGTH:
            i = int(_hash01(audio.hat_count - k, 7) * n) % n
            amount[i] = max(amount[i], (1 - age / GLINT_LENGTH) ** 2)
    colour = _bright(mix(_palette(pal, pos + 0.25), WHITE, GLINT_WHITE), GLINT_LEVEL)
    return [colour] * n, amount


def riser(n: int, audio: Audio, pal: Sequence[float], pos: float) -> tuple[list[RGB], list[float]]:
    """A build fills the strip from both ends towards the middle, in stripes running
    inwards, faster and whiter as it grows."""
    if audio.build <= 0:
        return [DARK] * n, [0.0] * n
    reach = audio.build * n / 2  # LEDs from each end
    phase = audio.travel * (RISER_SPEED[0] + (RISER_SPEED[1] - RISER_SPEED[0]) * audio.build)
    colour = _bright(mix(_palette(pal, pos + 0.25), WHITE, RISER_WHITE * audio.build),
                     RISER_LEVEL * (0.4 + 0.6 * audio.build))
    amount = []
    for i in range(n):
        d = min(i, n - 1 - i)  # LEDs from the nearer end
        stripe = 0.5 + 0.5 * math.sin(2 * math.pi * (0.35 * d - phase))
        amount.append(clamp01(reach - d) * (0.45 + 0.55 * stripe))
    return [colour] * n, amount


class Music(Effect):
    id = "music"
    name = "Hudba"
    pickable = False

    def render(self, ctx: Context) -> Picture:
        n = ctx.led_count
        audio = ctx.audio
        if audio is None:
            return Picture(leds=[DARK] * n, matrix=bars([0.0] * 8), matrix_brightness=0.6)
        scene = scene_number(audio)
        pal = PALETTES[scene % len(PALETTES)]
        shape = SHAPES[scene % len(SHAPES)]
        look = LOOKS[scene % len(LOOKS)]
        pos = colour_position(audio)

        leds = base(n, audio, pal, pos, look)
        for colours, amount in (riser(n, audio, pal, pos), snare(n, audio, pal, pos),
                                glints(n, audio, pal, pos)):
            leds = _over(leds, colours, amount)
        colours, amount = kick(n, audio, pal, pos, shape)
        leds = [_add(c, scale(k, f)) for c, k, f in zip(leds, colours, amount)]
        return Picture(leds=leds, matrix=bars(resample(audio.held or audio.bands, 8)), matrix_brightness=0.6)
