"""The spectrum from the main screen and the music effect (plan step 8)."""

import random

import pytest

from dod.engine import matrix as m
from dod.engine.color import luminance
from dod.engine.effects.base import Audio, Context
from dod.engine.effects.music import (HALF_TIME, PULSE_DECAY, PULSE_LENGTH, SCENE_BEATS, SCENES, SPARKLE_MAX,
                                      SPREAD_SECONDS, Music, colour_position, sparkles)
from dod.engine.output import OutputStage
from dod.music.audio import FADE, STALE, AudioInput

LOUD = [0.9] * 8 + [0.5] * 8 + [0.2] * 16  # loud lows, quiet highs


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_the_latest_spectrum():
    clock = Clock()
    audio = AudioInput(clock=clock)
    assert audio.current() is None  # nothing yet
    audio.push([0.1] * 32, beat=False)
    clock.t += 0.03
    audio.push(LOUD, beat=True)
    now = audio.current()
    assert now.bands == tuple(LOUD) and now.beat is True
    assert audio.beat is True


def test_stale_after_200_ms_it_fades_out_instead_of_freezing():
    clock = Clock()
    audio = AudioInput(clock=clock)
    audio.push([1.0] * 32, beat=True)
    start = clock.t
    clock.t = start + STALE - 0.01
    assert audio.current().bands[0] == 1.0  # still fresh
    clock.t = start + STALE + FADE / 2
    half = audio.current()
    assert half.bands[0] == pytest.approx(0.5) and half.beat is False
    clock.t = start + STALE + FADE + 0.01
    assert audio.current() is None


def test_the_delay_shows_the_spectrum_from_that_long_ago():
    clock = Clock()
    audio = AudioInput(delay=0.2, clock=clock)
    start = clock.t
    audio.push([0.1] * 32, beat=False)
    assert audio.current() is None  # it reaches the speaker 0.2 s from now
    clock.t = start + 0.21
    audio.push([0.9] * 32, beat=True)
    assert audio.current().bands[0] == pytest.approx(0.1)  # the loud one is still "in the speaker"
    clock.t = start + 0.42
    assert audio.current().bands[0] == pytest.approx(0.9)


def test_old_spectra_are_dropped():
    clock = Clock()
    audio = AudioInput(clock=clock)
    for _ in range(30 * 10):  # 10 s at 30 a second
        audio.push(LOUD, beat=False)
        clock.t += 1 / 30
    assert len(audio._spectra) <= 30 * 3 + 1


# --- what the light show needs from the past ---------------------------------


def test_the_last_beats_their_count_and_the_travel():
    clock = Clock()
    audio = AudioInput(clock=clock)
    for frame in range(30 * 3):  # 3 s, a beat every 0.5 s
        audio.push([0.5] * 32, beat=frame % 15 == 0)
        clock.t += 1 / 30
    clock.t -= 1 / 30
    now = audio.current()
    assert now.count == 6
    assert len(now.beats) == 4  # BEATS_KEPT, newest first
    assert now.beats == tuple(sorted(now.beats))
    assert now.beats[1] - now.beats[0] == pytest.approx(0.5)
    assert now.travel == pytest.approx(0.5 * (3 - 1 / 30), rel=0.01)  # loudness 0.5 for ~3 s


def test_travel_grows_faster_when_louder():
    def travel(level):
        clock = Clock()
        audio = AudioInput(clock=clock)
        for _ in range(30):
            audio.push([level] * 32, beat=False)
            clock.t += 1 / 30
        return audio.current(clock.t - 1 / 30).travel
    assert travel(0.8) == pytest.approx(4 * travel(0.2))


def test_beats_follow_the_delay_too():
    clock = Clock()
    audio = AudioInput(delay=0.2, clock=clock)
    audio.push([0.5] * 32, beat=False)
    clock.t += 0.1
    audio.push([0.5] * 32, beat=True)  # heard now, in the speaker 0.2 s later
    clock.t += 0.15
    assert audio.current().beats == () and audio.current().count == 0  # not yet
    clock.t += 0.1
    assert audio.current().count == 1 and audio.current().beats[0] == pytest.approx(0.05)


def test_the_bass_follows_the_song_and_kicks_add_it_up():
    def song(bass_level):
        clock = Clock()
        audio = AudioInput(clock=clock)
        for frame in range(30 * 6):  # 6 s, a kick every 0.5 s
            audio.push([bass_level] * 6 + [0.3] * 26, beat=frame % 15 == 0)
            clock.t += 1 / 30
        return audio.current(clock.t - 1 / 30)
    heavy, light = song(0.9), song(0.2)
    assert heavy.bass == pytest.approx(0.9, abs=0.05) and light.bass == pytest.approx(0.2, abs=0.05)
    assert heavy.kick_sum > 3 * light.kick_sum  # the same kicks, much more bass in them
    assert heavy.bass_travel > 3 * light.bass_travel


# --- the music effect ---------------------------------------------------------


def render(audio, n=10, t=1.0):
    return Music().render(Context(led_count=n, t=t, audio=audio))


def level(picture):
    return sum(luminance(c) for c in picture.leds) / len(picture.leds)


def kick(age, count=1, bands=(0.8,) * 6 + (0.4,) * 26, **past):
    """The moment `age` seconds after a kick (count 1: the first scene, the whole strip)."""
    return Audio(bands=bands, beats=(age,), count=count, **past)


def test_8_bars_on_the_8x8():
    p = render(Audio(bands=tuple(LOUD)))
    assert p.matrix == m.bars(m.resample(LOUD, 8))


def test_silence_is_dark():
    p = render(None)
    assert all(c == (0.0, 0.0, 0.0) for c in p.leds) and m.lit(p.matrix) == 0
    quiet = render(Audio(bands=(0.0,) * 32, beats=(2.0,), count=5))
    assert all(c == (0.0, 0.0, 0.0) for c in quiet.leds)  # a silent moment of a song: dark too


def test_a_kick_pulses_the_strip_and_it_fades_fast():
    between = level(render(kick(PULSE_LENGTH)))
    peak = level(render(kick(0.0)))
    assert peak > between + 0.4  # a big jump: the kick
    assert level(render(kick(PULSE_DECAY))) < peak * 0.5  # mostly gone after PULSE_DECAY
    assert between < 0.15  # in between: a dim background


def test_a_kick_with_more_bass_pulses_harder():
    soft = level(render(kick(0.0, bands=(0.2,) * 6 + (0.4,) * 26)))
    hard = level(render(kick(0.0, bands=(1.0,) * 6 + (0.4,) * 26)))
    assert hard > soft


def test_bassy_songs_change_colour_faster():
    def colour_after_kicks(bass):
        clock = Clock()
        audio = AudioInput(clock=clock)
        effect = Music()
        seen = []
        for frame in range(30 * 8):  # 8 s at 120 BPM
            audio.push([bass] * 6 + [0.4] * 26, beat=frame % 15 == 0)
            if frame % 15 == 1:  # just after each kick: the pulse's colour
                c = effect.render(Context(led_count=10, t=frame / 30, audio=audio.current())).leds[0]
                seen.append(tuple(round(v / max(c), 1) for v in c))  # the colour, not its brightness
            clock.t += 1 / 30
        changes = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
        return changes, colour_position(audio.current())
    heavy_changes, heavy_moved = colour_after_kicks(0.9)
    light_changes, light_moved = colour_after_kicks(0.2)
    assert heavy_moved > 3 * light_moved
    assert heavy_changes >= light_changes


def test_scenes_and_palettes_change_every_16_beats():
    pictures = [render(kick(0.05, count=1 + part * SCENE_BEATS)).leds for part in range(len(SCENES))]
    assert len(set(pictures)) == len(SCENES)


def test_the_centre_scene_spreads_out_from_the_middle():
    count = SCENE_BEATS + 1
    assert SCENES[1].__name__ == "centre"
    start = render(kick(0.0, count=count))
    lit = [i for i, c in enumerate(start.leds) if max(c) > 0.3]
    assert lit and all(3 <= i <= 6 for i in lit)  # just begun: the middle of 10 LEDs
    spread = render(kick(SPREAD_SECONDS, count=count))
    assert max(spread.leds[0]) > 0.3 and max(spread.leds[9]) > 0.3  # reached the ends


def test_the_halves_scene_alternates():
    count = 2 * SCENE_BEATS
    assert SCENES[2].__name__ == "halves"
    def left_minus_right(p):
        return sum(max(c) for c in p.leds[:5]) - sum(max(c) for c in p.leds[5:])
    assert left_minus_right(render(kick(0.02, count=count))) > 1  # an even kick: the left half
    assert left_minus_right(render(kick(0.02, count=count + 1))) < -1  # the next one: the right


def test_comets_fly_from_alternate_ends():
    count = 3 * SCENE_BEATS
    assert SCENES[3].__name__ == "comets"
    # the newest comet comes from beat number count - 1: even from the start, odd from the end
    calm = (0.5,) * 22 + (0.0,) * 10  # no treble: no sparkles in the way
    from_start = render(Audio(bands=calm, beats=(0.26,), count=count + 1))
    from_end = render(Audio(bands=calm, beats=(0.26,), count=count + 2))
    def head(p):
        return max(range(10), key=lambda i: max(p.leds[i]))
    assert head(from_start) >= 5 and head(from_end) <= 4


def test_fast_songs_pulse_on_every_second_kick():
    fast = (0.0, HALF_TIME - 0.05)  # kicks closer than HALF_TIME
    on = render(Audio(bands=(0.8,) * 32, beats=fast, count=2))
    off = render(Audio(bands=(0.8,) * 32, beats=fast, count=3))
    assert level(on) > level(off) + 0.3


def test_treble_sparkles_a_few_at_a_time():
    treble = Audio(bands=(0.0,) * 22 + (1.0,) * 10)
    bright = 0
    for frame in range(300):
        layer = sparkles(10, frame / 30, treble)
        on = sum(1 for c in layer if max(c) > 0)
        assert on <= SPARKLE_MAX
        bright += on
    assert bright > 50  # but plenty of them
    silent = Audio(bands=(0.5,) * 22 + (0.0,) * 10)
    assert all(max(c) == 0 for f in range(60) for c in sparkles(10, f / 30, silent))  # no treble, none


def test_the_same_moment_gives_the_same_picture():
    a = Audio(bands=tuple(LOUD), beats=(0.1, 0.6), count=21, travel=3.3, bass=0.6, bass_travel=2.0, kick_sum=7.5)
    assert render(a, t=2.5) == render(a, t=2.5)


@pytest.mark.parametrize("bpm", [90, 100, 110, 120, 128, 140, 150, 160, 174, 200])
@pytest.mark.parametrize("bass", [0.3, 0.9])
def test_a_whole_song_passes_the_flash_limit_untouched(bpm, bass):
    # backend.md 7.3: every kick is a pulse, and at most 3 flashes a second are allowed;
    # fast songs pulse half-time. Through AudioInput, like a real song, every scene.
    rng = random.Random(bpm)
    clock = Clock()
    audio = AudioInput(clock=clock)
    stage = OutputStage(brightness=1.0, power_limit_ma=100_000)
    effect = Music()
    period = 60 / bpm
    next_beat, last = 0.5, -1.0
    start = clock.t
    for frame in range(30 * 50):  # 50 s: every scene and palette
        t = frame / 30
        clock.t = start + t
        beat = False
        if t >= next_beat:
            beat = t - last >= 0.34  # beat.ts's GAP
            last = t if beat else last
            next_beat += period
        hit = max(0.0, 1 - (t % period) / 0.15)
        bands = ([min(1.0, bass * (0.5 + 0.5 * hit) + rng.uniform(-0.1, 0.1)) for _ in range(8)]
                 + [0.5 + rng.uniform(-0.15, 0.15) for _ in range(14)]
                 + [min(1.0, max(0.0, 0.6 + rng.uniform(-0.3, 0.3))) for _ in range(10)])
        audio.push(bands, beat)
        out = stage.apply(effect.render(Context(led_count=10, t=t, audio=audio.current())), now=clock.t)
        assert not out.strip_held and not out.matrix_held, f"held at {t:.2f} s"
