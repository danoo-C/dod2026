"""The spectrum from the main screen and the music effect (plan step 8)."""

import pytest

from dod.engine import matrix as m
from dod.engine.effects.base import Audio, Context
from dod.engine.effects.music import Music
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
    assert audio.current() == Audio(bands=tuple(LOUD), beat=True)
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


# --- the music effect ---------------------------------------------------------


def render(audio, n=10, t=1.0):
    return Music().render(Context(led_count=n, t=t, audio=audio))


def test_the_spectrum_on_the_strip_and_8_bars_on_the_8x8():
    p = render(Audio(bands=tuple(LOUD)))
    assert p.matrix == m.bars(m.resample(LOUD, 8))
    assert max(p.leds[0]) > max(p.leds[-1])  # low bands (first LEDs) loud, highs quiet


def test_silence_is_dark():
    p = render(None)
    assert all(c == (0.0, 0.0, 0.0) for c in p.leds) and m.lit(p.matrix) == 0


def test_a_beat_lifts_the_strip_a_little():
    quiet = render(Audio(bands=(0.3,) * 32))
    beat = render(Audio(bands=(0.3,) * 32, beat=True))
    assert max(beat.leds[0]) > max(quiet.leds[0])


def test_a_2_hz_beat_passes_the_flash_limit_untouched():
    # backend.md 7.3: a beat flash at 120 BPM is 2 a second and must not be held
    stage = OutputStage(brightness=1.0, power_limit_ma=100_000)
    for frame in range(10 * 30):
        t = frame / 30
        beat = (t % 0.5) < 0.1
        bands = tuple([1.0 if beat else 0.3] * 32)
        out = stage.apply(render(Audio(bands=bands, beat=beat), t=t), now=t)
        assert not out.strip_held and not out.matrix_held, f"held at {t:.2f} s"
