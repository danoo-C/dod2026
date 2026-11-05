"""The spectrum from the main screen, what is found in it, and the music effect (plan step 8)."""

import random

import pytest

from dod.engine import matrix as m
from dod.engine.color import luminance
from dod.engine.effects.base import Audio, Context
from dod.engine.effects import music as mu
from dod.engine.effects.music import Music
from dod.engine.output import OutputStage
from dod.music import audio as au
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


# --- snares, hi-hats, and the song's shape ---------------------------------------

QUIET_MIDS = [0.6] * 12 + [0.2] * 20  # bass and a little else


def feed(audio, clock, seconds, bands, beat_every=None, extra=None):
    """Push `seconds` of spectra; a kick every `beat_every` s; extra(frame) may change the bands."""
    for frame in range(round(seconds * 30)):
        b = list(bands)
        if extra is not None:
            b = extra(frame, b)
        beat = beat_every is not None and frame % round(beat_every * 30) == 0
        audio.push(b, beat)
        clock.t += 1 / 30
    clock.t -= 1 / 30
    return audio.current()


def with_hits(first, last, every, height=0.5):
    """Bands first..last jump by `height` for one frame every `every` frames."""
    def change(frame, b):
        if frame % every == 0:
            for i in range(first, last):
                b[i] = min(1.0, b[i] + height)
        return b
    return change


def test_snares_are_onsets_of_the_mid_bands():
    clock = Clock()
    audio = AudioInput(clock=clock)
    first, last = au.SNARE_BANDS
    now = feed(audio, clock, 4, QUIET_MIDS, extra=with_hits(first, last, 15))  # 2 a second
    assert 7 <= now.snare_count <= 8
    assert now.snares and now.snares[0] < 0.5
    steady = feed(AudioInput(clock=clock), clock, 4, [0.5] * 32)
    assert steady.snare_count == 0 and steady.hat_count == 0  # a steady sound has no onsets


def test_hats_are_onsets_of_the_top_bands():
    clock = Clock()
    audio = AudioInput(clock=clock)
    first, last = au.HAT_BANDS
    now = feed(audio, clock, 4, QUIET_MIDS, extra=with_hits(first, last, 5))  # 6 a second
    assert now.hat_count >= 20 and now.snare_count == 0
    assert len(now.hats) == au.HATS_KEPT


def test_onsets_never_closer_than_their_gap():
    clock = Clock()
    audio = AudioInput(clock=clock)
    first, last = au.SNARE_BANDS
    now = feed(audio, clock, 3, QUIET_MIDS, extra=with_hits(first, last, 2))  # every second frame
    assert now.snare_count <= 3 / au.SNARE.gap + 1


def test_level_follows_the_loudness():
    clock = Clock()
    audio = AudioInput(clock=clock)
    assert feed(audio, clock, 2, [0.4] * 32).level == pytest.approx(0.4, abs=0.01)
    assert feed(audio, clock, 2, [0.1] * 32).level == pytest.approx(0.1, abs=0.01)


def test_calm_without_kicks_and_back_with_them():
    clock = Clock()
    audio = AudioInput(clock=clock)
    assert feed(audio, clock, 4, LOUD, beat_every=0.5).calm < 0.1
    assert feed(audio, clock, 5, LOUD).calm > 0.9  # no kicks for 5 s
    assert feed(audio, clock, 4, LOUD, beat_every=0.5).calm < 0.1


def test_calm_when_the_bass_goes_even_if_a_kick_is_found_now_and_then():
    clock = Clock()
    audio = AudioInput(clock=clock)
    feed(audio, clock, 6, [0.8] * 6 + [0.4] * 26, beat_every=0.5)  # the loudest bass: 0.8
    breakdown = feed(audio, clock, 8, [0.1] * 6 + [0.4] * 26, beat_every=1.0)
    assert breakdown.calm > 0.9


def test_a_rising_calm_part_is_a_build():
    clock = Clock()
    audio = AudioInput(clock=clock)
    feed(audio, clock, 4, LOUD, beat_every=0.5)
    steady = feed(audio, clock, 8, [0.2] * 32)
    assert steady.calm > 0.9 and steady.build < 0.2  # calm, but not going anywhere
    rising = feed(audio, clock, au.BUILD_SECONDS + 4, [0.2] * 32,
                  extra=lambda frame, b: [min(1.0, v + frame / 30 * 0.04) for v in b])
    assert rising.build > 0.9


def test_a_snare_roll_is_a_build():
    clock = Clock()
    audio = AudioInput(clock=clock)
    feed(audio, clock, 4, LOUD, beat_every=0.5)
    first, last = au.SNARE_BANDS
    roll = feed(audio, clock, au.BUILD_SECONDS + 4, QUIET_MIDS, extra=with_hits(first, last, 6))  # 5 a second
    assert roll.build > 0.9


def test_a_kick_after_a_calm_part_is_a_drop_and_ends_it():
    clock = Clock()
    audio = AudioInput(clock=clock)
    feed(audio, clock, 4, LOUD, beat_every=0.5)
    assert audio.current().drop_count == 0  # the song's first kicks: no calm before them
    feed(audio, clock, au.DROP_CALM + 2, [0.2] * 32)
    clock.t += 1 / 30
    audio.push(LOUD, True)
    now = audio.current()
    assert now.drop_count == 1 and now.drop == 0.0
    assert now.calm == 0.0 and now.build == 0.0
    later = feed(audio, clock, 3, LOUD, beat_every=0.5)
    assert later.drop_count == 1 and later.calm < 0.1  # the kicks after it are no drops


def test_a_short_pause_in_the_kicks_is_no_drop():
    clock = Clock()
    audio = AudioInput(clock=clock)
    for _ in range(4):
        feed(audio, clock, 3, LOUD, beat_every=0.5)
        feed(audio, clock, au.CALM_AFTER + 1, LOUD)  # calm, but shorter than DROP_CALM
    assert audio.current().drop_count == 0


def test_a_new_song_starts_its_loudest_bass_over():
    clock = Clock()
    audio = AudioInput(clock=clock)
    feed(audio, clock, 6, [0.9] * 6 + [0.4] * 26, beat_every=0.5)
    clock.t += au.SONG_GAP + 1  # the next song
    quieter = feed(audio, clock, 6, [0.3] * 6 + [0.4] * 26, beat_every=0.5)
    assert quieter.calm < 0.1  # not a breakdown: just a song with less bass


# --- the music effect ---------------------------------------------------------


def render(audio, n=10, t=1.0):
    return Music().render(Context(led_count=n, t=t, audio=audio))


def level(picture):
    return sum(luminance(c) for c in picture.leds) / len(picture.leds)


BANDS = (0.8,) * 6 + (0.4,) * 26


def moment(count=1, **fields):
    """A moment of a loud song: kick number `count` happened `beats` ago (no kick: beats=())."""
    fields.setdefault("bands", BANDS)
    fields.setdefault("level", 0.4)
    return Audio(count=count, **fields)


def scene_with(shape):
    """A kick count in the scene with this shape (and no drop)."""
    for scene in range(100):
        if mu.SHAPES[scene % len(mu.SHAPES)] is shape:
            return scene * mu.SCENE_BEATS + 2
    raise AssertionError


def test_8_bars_on_the_8x8():
    p = render(Audio(bands=tuple(LOUD)))
    assert p.matrix == m.bars(m.resample(LOUD, 8))
    held = (0.5,) * 32
    assert render(Audio(bands=tuple(LOUD), held=held)).matrix == m.bars(m.resample(held, 8))  # the falling bars


def test_the_bars_jump_up_and_fall_slowly():
    clock = Clock()
    audio = AudioInput(clock=clock)
    feed(audio, clock, 0.5, [0.1] * 32)
    clock.t += 1 / 30
    audio.push([0.9] * 32, False)
    assert audio.current().held[0] == pytest.approx(0.9)  # up at once
    now = feed(audio, clock, 0.5, [0.1] * 32)
    assert now.held[0] == pytest.approx(0.9 - au.BAR_FALL * 0.5, abs=0.03)  # down slowly
    assert now.bands[0] == pytest.approx(0.1)


def test_silence_is_dark():
    p = render(None)
    assert all(c == (0.0, 0.0, 0.0) for c in p.leds) and m.lit(p.matrix) == 0
    quiet = render(Audio(bands=(0.0,) * 32, beats=(2.0,), count=5))
    assert all(c == (0.0, 0.0, 0.0) for c in quiet.leds)  # a silent moment of a song: dark too


def test_the_base_is_colourful_and_moves():
    a = render(moment(travel=1.0))
    b = render(moment(travel=1.2))
    assert len({tuple(round(v, 1) for v in c) for c in a.leds}) >= 4  # not one colour
    assert a.leds != b.leds  # it moves on with the music


def test_the_base_keeps_its_brightness_whatever_its_colours():
    # the flash limit counts the strip's average brightness: the base's pattern and
    # colours may change at any speed, its brightness only with the loudness
    levels = [level(render(moment(count=c, travel=tr, kick_sum=ks)))
              for c in (1, mu.SCENE_BEATS + 1, 2 * mu.SCENE_BEATS + 1)
              for tr in (0.0, 0.37, 1.1) for ks in (0.0, 1.3, 2.9)]
    assert max(levels) - min(levels) < 0.1
    assert level(render(moment(level=0.1))) < level(render(moment(level=0.4))) * 0.5  # quieter: dimmer


def test_a_kick_hits_and_fades_fast():
    count = scene_with(mu.flood)
    between = level(render(moment(count=count, beats=(mu.HIT_LENGTH,))))
    peak = level(render(moment(count=count, beats=(0.0,))))
    assert peak > between + 0.3  # a big jump: the kick
    assert level(render(moment(count=count, beats=(mu.HIT_DECAY * 2,)))) < between + 0.3 * 0.5  # mostly gone


def test_a_kick_with_more_bass_hits_harder():
    count = scene_with(mu.flood)
    soft = level(render(moment(count=count, beats=(0.0,), bands=(0.2,) * 6 + (0.4,) * 26)))
    hard = level(render(moment(count=count, beats=(0.0,), bands=(1.0,) * 6 + (0.4,) * 26)))
    assert hard > soft


def test_every_kick_moves_the_colours_on():
    a = render(moment(beats=(0.05,), kick_sum=1.0))
    b = render(moment(beats=(0.05,), kick_sum=1.8))
    assert a.leds != b.leds


def test_bassy_songs_change_colour_faster():
    def colour_moved(bass):
        clock = Clock()
        audio = AudioInput(clock=clock)
        for frame in range(30 * 8):  # 8 s at 120 BPM
            audio.push([bass] * 6 + [0.4] * 26, beat=frame % 15 == 0)
            clock.t += 1 / 30
        return mu.colour_position(audio.current())
    assert colour_moved(0.9) > 3 * colour_moved(0.2)


def test_scenes_change_every_phrase_and_at_a_drop():
    assert mu.scene_number(moment(count=mu.SCENE_BEATS - 1)) == 0
    assert mu.scene_number(moment(count=mu.SCENE_BEATS)) == 1
    assert mu.scene_number(moment(count=5, drop_count=1)) == 1
    pictures = {render(moment(count=1 + s * mu.SCENE_BEATS, beats=(0.05,))).leds for s in range(len(mu.SHAPES))}
    assert len(pictures) == len(mu.SHAPES)


def test_the_burst_spreads_out_from_the_middle():
    count = scene_with(mu.burst)
    start = render(moment(count=count, beats=(0.0,), level=0.0))  # no base: only the hit
    lit = [i for i, c in enumerate(start.leds) if max(c) > 0.2]
    assert lit and all(3 <= i <= 6 for i in lit)
    spread = render(moment(count=count, beats=(mu.SPREAD_SECONDS,), level=0.0))
    assert max(spread.leds[0]) > 0.2 and max(spread.leds[9]) > 0.2


def test_the_halves_alternate():
    count = scene_with(mu.halves)
    def left_minus_right(p):
        return sum(max(c) for c in p.leds[:5]) - sum(max(c) for c in p.leds[5:])
    assert left_minus_right(render(moment(count=count, beats=(0.02,), level=0.0))) > 1
    assert left_minus_right(render(moment(count=count + 1, beats=(0.02,), level=0.0))) < -1


def test_comets_fly_from_alternate_ends():
    count = scene_with(mu.comet)
    def head(p):
        return max(range(10), key=lambda i: max(p.leds[i]))
    assert head(render(moment(count=count, beats=(0.16,), level=0.0))) >= 5
    assert head(render(moment(count=count + 1, beats=(0.16,), level=0.0))) <= 4


def test_scattered_spots_move_with_every_kick():
    count = scene_with(mu.scatter)
    a = render(moment(count=count, beats=(0.0,), level=0.0))
    b = render(moment(count=count + 1, beats=(0.0,), level=0.0))
    assert [max(c) > 0.2 for c in a.leds] != [max(c) > 0.2 for c in b.leds]


def test_fast_songs_hit_hard_on_every_second_kick():
    fast = (0.0, mu.HALF_TIME - 0.05)  # kicks closer than HALF_TIME
    count = scene_with(mu.flood)
    on = render(moment(count=count, beats=fast))
    off = render(moment(count=count + 1, beats=fast))
    between = render(moment(count=count + 1, beats=(mu.HIT_LENGTH,)))
    assert level(on) > level(off) + 0.2
    assert level(off) - level(between) < 0.15  # the small one: under a flash
    assert off.leds != between.leds  # but it still shows


def test_a_snare_lights_one_side_then_the_other():
    def sides(p):
        return sum(max(c) for c in p.leds[:3]), sum(max(c) for c in p.leds[-3:])
    base_left, base_right = sides(render(moment()))
    left, right = sides(render(moment(snares=(0.0,), snare_count=1)))
    assert left != base_left and right == base_right
    left, right = sides(render(moment(snares=(0.0,), snare_count=2)))
    assert right != base_right and left == base_left
    assert render(moment(snares=(mu.SNARE_LENGTH,), snare_count=2)).leds == render(moment()).leds  # gone


def test_a_hat_glints_on_one_led():
    calm = render(moment())
    glint = render(moment(hats=(0.0,), hat_count=5))
    changed = [i for i in range(10) if glint.leds[i] != calm.leds[i]]
    assert len(changed) == 1
    elsewhere = {next(i for i in range(10) if render(moment(hats=(0.0,), hat_count=k)).leds[i] != calm.leds[i])
                 for k in range(1, 30)}
    assert len(elsewhere) >= 5  # a different LED from one hat to the next


def test_calm_is_dimmer_and_slower():
    loud = render(moment(level=0.4))
    calm = render(moment(level=0.4, calm=1.0))
    assert level(calm) < level(loud)


def test_a_build_fills_from_the_ends():
    start = render(moment(level=0.2, calm=1.0, build=0.2, travel=0.0))
    full = render(moment(level=0.2, calm=1.0, build=1.0, travel=0.0))
    plain = render(moment(level=0.2, calm=1.0, travel=0.0))
    assert start.leds[0] != plain.leds[0] and start.leds[4] == plain.leds[4]  # the ends first
    assert full.leds[4] != plain.leds[4]  # then all of it
    assert level(full) > level(start)


def test_a_drop_hits_the_whole_strip_white():
    p = render(moment(count=40, beats=(0.0,), drop=0.0, drop_count=1))
    assert all(min(c) > 0.3 for c in p.leds)
    assert level(render(moment(count=40, beats=(0.5,), drop=0.5, drop_count=1))) > level(
        render(moment(count=40, beats=(0.5,))))  # and fades slower than a kick


def test_the_same_moment_gives_the_same_picture():
    a = Audio(bands=tuple(LOUD), beats=(0.1, 0.6), count=21, travel=3.3, bass=0.6, bass_travel=2.0, kick_sum=7.5,
              snares=(0.05,), snare_count=3, hats=(0.02, 0.1), hat_count=9, level=0.35, calm=0.2, build=0.1)
    assert render(a, t=2.5) == render(a, t=2.5)


def test_any_led_count_works():
    for n in (1, 2, 3, 10, 60):
        a = moment(beats=(0.03,), snares=(0.01,), snare_count=1, hats=(0.0,), hat_count=1, build=0.5, calm=1.0)
        assert render(a, n=n).led_count == n


# --- whole songs and the flash limit ---------------------------------------------


def song_bands(rng, t, period, bass, *, kick_on, section):
    """One spectrum of a simulated song: a kick, a snare on 2 and 4, hats on the 8ths."""
    phase = t % period
    hit = max(0.0, 1 - phase / 0.15) if kick_on else 0.0
    snare = max(0.0, 1 - ((t + period) % (2 * period)) / 0.12) if section != "build" else max(
        0.0, 1 - (t % (period / 4)) / 0.06)
    hat = max(0.0, 1 - (t % (period / 2)) / 0.05)
    low = bass * (0.5 + 0.5 * hit) if section != "breakdown" else 0.1
    rise = min(1.0, (t % 16) / 16) * 0.3 if section == "build" else 0.0
    return ([min(1.0, max(0.0, low + rng.uniform(-0.1, 0.1))) for _ in range(8)]
            + [min(1.0, max(0.0, 0.35 + rise + 0.4 * snare + rng.uniform(-0.1, 0.1))) for _ in range(16)]
            + [min(1.0, max(0.0, 0.3 + rise + 0.5 * hat + rng.uniform(-0.15, 0.15))) for _ in range(8)])


@pytest.mark.parametrize("bpm", [90, 110, 128, 140, 160, 174, 200])
@pytest.mark.parametrize("bass", [0.3, 0.9])
def test_a_whole_song_passes_the_flash_limit_untouched(bpm, bass, monkeypatch):
    # backend.md 7.3/7.5: only kicks and drops are flashes; the rest moves without
    # changing the strip's brightness by a step. Through AudioInput, like a real song:
    # verse, breakdown, build, drop – and every scene, changing every 8 kicks here.
    monkeypatch.setattr(mu, "SCENE_BEATS", 8)
    rng = random.Random(bpm)
    clock = Clock()
    audio = AudioInput(clock=clock)
    stage = OutputStage(brightness=1.0, power_limit_ma=100_000)
    effect = Music()
    period = 60 / bpm
    next_beat, last = 0.5, -1.0
    start = clock.t
    sections = [(0, "verse"), (24, "breakdown"), (31, "build"), (43, "verse")]
    for frame in range(30 * 60):  # 60 s
        t = frame / 30
        clock.t = start + t
        section = [name for since, name in sections if t >= since][-1]
        kick_on = section == "verse"
        beat = False
        if t >= next_beat:
            beat = kick_on and t - last >= 0.34  # beat.ts's GAP
            last = t if beat else last
            next_beat += period
        audio.push(song_bands(rng, t, period, bass, kick_on=kick_on, section=section), beat)
        out = stage.apply(effect.render(Context(led_count=10, t=t, audio=audio.current())), now=clock.t)
        assert not out.strip_held and not out.matrix_held, f"held at {t:.2f} s ({section})"
    now = audio.current()
    assert now.drop_count == 1 and now.snare_count > 50 and now.hat_count > 100  # it all happened
