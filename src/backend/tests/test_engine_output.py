"""From Picture to output: brightness, flash limit, power limit, preview, gamma
(docs/backend.md 7.3)."""

import math

import pytest

from dod.engine import matrix as m
from dod.engine.color import BLACK, WHITE, luminance
from dod.engine.output import FlashLimiter, OutputStage, estimated_current_ma
from dod.engine.picture import Picture

FPS = 30


def stage(brightness=1.0, power_limit_ma=100_000):
    return OutputStage(brightness=brightness, power_limit_ma=power_limit_ma)


def strip(color, n=10):
    return Picture(leds=[color] * n)


def preview_level(out):
    leds = out.preview.leds
    return sum(luminance((r / 255, g / 255, b / 255)) for r, g, b in leds) / len(leds)


def run(pictures, st=None):
    """Feed one picture per frame at 30 fps; returns [(time, output)]."""
    st = st or stage()
    return [(i / FPS, st.apply(p, now=i / FPS)) for i, p in enumerate(pictures)]


def max_in_any_window(times, window=1.0):
    """The most events inside any half-open window [a, a + window)."""
    return max((sum(1 for u in times if t <= u < t + window) for t in times), default=0)


# --- brightness, gamma, preview -----------------------------------------------


def test_gamma_keeps_0_and_1():
    out = stage().apply(Picture(leds=[WHITE, BLACK]), now=0)
    assert out.hardware.leds == ((255, 255, 255), (0, 0, 0))
    assert out.preview.leds == ((255, 255, 255), (0, 0, 0))


def test_the_preview_is_before_gamma():
    out = stage().apply(strip((0.5, 0.5, 0.5), 1), now=0)
    assert out.preview.leds[0] == (128, 128, 128)
    assert out.hardware.leds[0] == (round(0.5 ** 2.2 * 255),) * 3 == (55, 55, 55)
    assert out.preview.hex_leds() == ["#808080"]


def test_master_brightness():
    out = stage(brightness=0.5).apply(Picture(leds=[WHITE], matrix=m.FULL, matrix_brightness=1.0), now=0)
    assert out.preview.leds[0] == (128, 128, 128)
    assert out.hardware.matrix_brightness == round(0.5 * 15)


def test_bad_values_from_an_effect_are_clamped():
    out = stage().apply(Picture(leds=[(1.5, -0.2, math.nan)]), now=0)
    assert out.hardware.leds[0] == (255, 0, 0)


def test_brightness_must_be_0_to_1():
    st = stage()
    st.brightness = 0.3
    assert st.brightness == 0.3
    for bad in (-0.1, 1.1, math.nan):
        with pytest.raises(ValueError):
            st.brightness = bad


def test_the_matrix_goes_dark_when_its_brightness_rounds_to_0():
    # the MAX7219's lowest setting still glows, so brightness 0 means no pixels
    out = stage().apply(Picture(leds=[BLACK], matrix=m.FULL, matrix_brightness=0.02), now=0)
    assert out.hardware.matrix_brightness == 0 and out.hardware.matrix == m.BLANK
    assert out.preview.matrix == m.BLANK
    out = stage().apply(Picture(leds=[BLACK], matrix=m.FULL, matrix_brightness=0.1), now=0)
    assert out.hardware.matrix_brightness == 2 and out.hardware.matrix == m.FULL


# --- power limit --------------------------------------------------------------


def test_the_power_limit_holds_exactly_for_full_white():
    out = stage(power_limit_ma=1500).apply(strip(WHITE, 60), now=0)  # 60 LEDs: 3600 mA unlimited
    assert out.power_scale < 1
    current = estimated_current_ma(out.hardware)
    assert current <= 1500
    assert current > 1500 - 180 * 20 / 255  # rounding down loses at most one step per channel
    # the preview shows the same dimmed picture (before gamma)
    seen = sum((c / 255) ** 2.2 for led in out.preview.leds for c in led) * 20
    assert seen == pytest.approx(1500, rel=0.02)


def test_under_the_limit_nothing_changes():
    out = stage(power_limit_ma=1500).apply(strip(WHITE, 10), now=0)  # 600 mA
    assert out.power_scale == 1 and out.hardware.leds[0] == (255, 255, 255)


@pytest.mark.parametrize("color", [(1, 0, 0), (0.7, 0.2, 1.0), (0.3, 0.3, 0.3)])
def test_the_power_limit_holds_for_any_colour(color):
    out = stage(power_limit_ma=300).apply(strip(color, 60), now=0)
    assert estimated_current_ma(out.hardware) <= 300


def test_the_power_limit_counts_only_the_strip():
    out = stage(power_limit_ma=1).apply(Picture(leds=[BLACK], matrix=m.FULL, matrix_brightness=1), now=0)
    assert out.power_scale == 1 and out.hardware.matrix == m.FULL


# --- flash limit: the strip ---------------------------------------------------


def strobe(hz, seconds, on=WHITE, off=BLACK):
    """One picture per frame of an on/off strobe at `hz` flashes per second."""
    return [strip(on if math.floor(i / FPS * hz * 2) % 2 == 0 else off) for i in range(int(seconds * FPS))]


def test_a_20_hz_strobe_gets_at_most_3_flashes_a_second():
    frames = run(strobe(20, 4))
    levels = [round(preview_level(out), 3) for _, out in frames]
    assert set(levels) <= {0.0, 1.0}  # a held frame is a real earlier frame, never something in between
    changes = [t for (t, _), a, b in zip(frames[1:], levels, levels[1:]) if a != b]
    assert max_in_any_window(changes) <= 6
    assert any(out.strip_held for _, out in frames)
    assert len(changes) >= 6 * 3  # it isn't simply frozen


def test_a_2_hz_beat_passes_untouched():
    frames = run(strobe(2, 4))
    assert not any(out.strip_held for _, out in frames)
    expected = [255 if math.floor(i / FPS * 4) % 2 == 0 else 0 for i in range(len(frames))]
    assert [out.hardware.leds[0][0] for _, out in frames] == expected


def test_short_beat_flashes_pass_untouched():
    # 120 BPM: a 100 ms flash twice a second, like the music mode's beat
    pictures = [strip(WHITE if (i / FPS) % 0.5 < 0.1 else BLACK) for i in range(4 * FPS)]
    frames = run(pictures)
    assert not any(out.strip_held for _, out in frames)


def test_flicker_below_the_step_is_never_limited():
    # +-0.08 around 0.5 at 30 Hz: changes, but none of them big enough to count
    pictures = [strip((0.5 + (0.08 if i % 2 else -0.08),) * 3) for i in range(3 * FPS)]
    assert not any(out.strip_held for _, out in run(pictures))


def test_a_fade_is_one_transition():
    lim = FlashLimiter()
    for i in range(61):  # 0 -> 1 in half a second
        lim.show(i / 60, now=i / 120)
    assert lim.count(now=0.5) == 1
    assert lim.transition(0.85) == 0  # 0.15 below the peak: not yet
    assert lim.transition(0.8) == -1  # 0.2 below it: a transition


def test_the_limiter_counts_steps_from_the_last_peak():
    lim = FlashLimiter()
    lim.show(0.0, 0.0)
    assert lim.transition(0.19) == 0 and lim.transition(0.2) == 1
    lim.show(0.5, 0.1)  # up
    lim.show(0.9, 0.2)  # still going up: the peak follows
    assert lim.transition(0.75) == 0 and lim.transition(0.7) == -1
    lim.show(0.7, 0.3)  # down
    assert lim.transition(0.85) == 0 and lim.transition(0.9) == 1


# --- flash limit: the 8x8 -----------------------------------------------------


def blink(hz, seconds, still=WHITE):
    """The 8x8 fully on and off at `hz`, the strip steady."""
    return [Picture(leds=[still] * 10, matrix=m.FULL if math.floor(i / FPS * hz * 2) % 2 == 0 else m.BLANK,
                    matrix_brightness=1.0) for i in range(int(seconds * FPS))]


def test_the_8x8_is_limited_separately():
    frames = run(blink(20, 4))
    lit = [m.lit(out.hardware.matrix) for _, out in frames]
    changes = [t for (t, _), a, b in zip(frames[1:], lit, lit[1:]) if a != b]
    assert max_in_any_window(changes) <= 6
    assert any(out.matrix_held for _, out in frames)
    assert not any(out.strip_held for _, out in frames)  # the steady strip isn't touched


def test_a_limited_strip_doesnt_hold_the_8x8():
    # the 8x8 moves a dot around its edge (never a flash) while the strip strobes
    path = m.border()
    pictures = [Picture(leds=p.leds, matrix=m.from_pixels([path[i % len(path)]]), matrix_brightness=0.5)
                for i, p in enumerate(strobe(20, 2))]
    frames = run(pictures)
    assert any(out.strip_held for _, out in frames)
    assert not any(out.matrix_held for _, out in frames)
    assert [out.hardware.matrix for _, out in frames] == [p.matrix for p in pictures]


def test_a_new_led_count_starts_over():
    st = stage()
    st.apply(strip(WHITE, 10), now=0)
    out = st.apply(strip(BLACK, 12), now=0.03)
    assert out.hardware.led_count == 12 and not out.strip_held
