"""Every effect, with every parameter at its extremes (docs/backend.md 12)."""

import math

import pytest

from dod.engine import matrix as m
from dod.engine.color import luminance
from dod.engine.effects import EFFECTS, PRESETS
from dod.engine.effects.strobe import Strobe
from dod.engine.effects.base import Context
from dod.engine.output import OutputStage

LED_COUNTS = (1, 10, 60)
TIMES = (0.0, 0.5, 7.3, 1000.0)


def param_sets(effect):
    """The defaults, then each parameter at each of its samples (the others at default)."""
    yield effect.defaults()
    for p in effect.params:
        for value in p.samples():
            yield effect.defaults() | {p.name: value}


CASES = [(effect, params) for effect in EFFECTS.values() for params in param_sets(effect)]
IDS = [f"{e.id}-{'-'.join(f'{k}={v}' for k, v in p.items() if v != e.defaults()[k]) or 'defaults'}" for e, p in CASES]


@pytest.mark.parametrize("effect, params", CASES, ids=IDS)
@pytest.mark.parametrize("n", LED_COUNTS)
def test_the_picture_has_the_right_shape(effect, params, n):
    for t in TIMES:
        picture = effect().render(Context(led_count=n, t=t, params=params))
        assert picture.led_count == n
        for led in picture.leds:
            for c in led:
                assert math.isfinite(c) and -1e-9 <= c <= 1 + 1e-9, (t, led)
        assert len(picture.matrix) == 8
        assert 0 <= picture.matrix_brightness <= 1


@pytest.mark.parametrize("effect, params", CASES, ids=IDS)
def test_same_context_same_picture(effect, params):
    for t in TIMES:
        ctx = Context(led_count=10, t=t, params=params)
        assert effect().render(ctx) == effect().render(ctx)


@pytest.mark.parametrize("effect, params", CASES, ids=IDS)
def test_no_preset_needs_the_flash_limit(effect, params):
    # the limit is a safety net; with any parameter, the effects stay far below it
    stage = OutputStage(brightness=1.0, power_limit_ma=10_000)
    instance = effect()
    for frame in range(5 * 30):
        t = frame / 30
        out = stage.apply(instance.render(Context(led_count=10, t=t, params=params)), now=t)
        assert not out.strip_held and not out.matrix_held, f"held at {t:.2f} s"


def render(effect_id, t, n=10, **params):
    effect = EFFECTS[effect_id]
    return effect().render(Context(led_count=n, t=t, params=effect.defaults() | params))


def level(picture):
    """The strip's flash level (backend.md 7.3): average perceived brightness."""
    return sum(luminance(c) for c in picture.leds) / picture.led_count


def test_the_rainbow_moves_and_shows_its_arc():
    pictures = [render("rainbow", f / 30) for f in range(90)]
    assert len({p.leds for p in pictures}) > 80  # changes every frame
    assert {p.matrix for p in pictures} == {m.ICONS["rainbow"]}


# --- the 8x8 in manual mode (tech-spec 5.3): every preset its own icon ---------


def test_every_preset_shows_its_own_8x8():
    at = {pid: render(pid, 0.3).matrix for pid in PRESETS}
    assert len(set(at.values())) == len(PRESETS), at  # no two alike
    for pid in PRESETS:
        # something to see (the comet starts as a single pixel entering the diagonal)
        assert max(m.lit(render(pid, f / 30).matrix) for f in range(60)) >= 4, pid


@pytest.mark.parametrize("pid", ["fire", "police", "breathe", "comet", "strobe"])
def test_the_animated_icons_move(pid):
    assert len({render(pid, f / 30).matrix for f in range(4 * 30)}) > 1


# --- strobe ---------------------------------------------------------------------

STROBE_RATES = [round(0.5 + 0.1 * i, 1) for i in range(16)]  # every step of its slider


@pytest.mark.parametrize("rate", STROBE_RATES)
@pytest.mark.parametrize("n", LED_COUNTS)
def test_the_strobe_stays_within_the_flash_limit_at_every_speed(rate, n):
    stage = OutputStage(brightness=1.0, power_limit_ma=100_000)
    for frame in range(10 * 30):
        t = frame / 30
        out = stage.apply(render("strobe", t, n=n, rate=rate), now=t)
        assert not out.strip_held and not out.matrix_held, f"held at {t:.2f} s"


def test_the_strobe_flashes_as_often_as_it_says():
    assert Strobe.params[0].max < 3  # the flash limit is 3 a second; the preset stays under it
    for rate in (0.5, 1.0, 2.0):
        on = [level(render("strobe", f / 30, rate=rate)) > 0.5 for f in range(10 * 30)]
        flashes = sum(1 for a, b in zip(on, on[1:]) if b and not a) + on[0]
        assert flashes == round(10 * rate), rate
        assert 2 <= max(len(run) for run in "".join("#" if x else "." for x in on).split(".")) <= 4  # ~0.1 s


def test_the_strobes_8x8_lights_up_with_each_flash():
    assert render("strobe", 0.0).matrix == m.FULL
    assert render("strobe", 0.5).matrix == m.ICONS["lightning"]


# --- police ---------------------------------------------------------------------


def test_the_police_halves_take_turns():
    left, right = render("police", 0.0), render("police", 1.0)  # speed 1: one swap a second
    assert luminance(left.leds[0]) > luminance(right.leds[0])
    assert luminance(left.leds[9]) < luminance(right.leds[9])
    assert left.matrix != right.matrix and m.lit(left.matrix) == m.lit(right.matrix)


def test_the_police_strip_keeps_its_brightness_when_the_halves_swap():
    # no flash: the average barely moves (backend.md 7.3 counts 0.2 as a transition)
    for colours in ("redblue", "amber"):
        assert abs(level(render("police", 0.0, colours=colours)) - level(render("police", 1.0, colours=colours))) < 0.1


def test_a_single_led_police_alternates_the_colours():
    a, b = render("police", 0.0, n=1).leds[0], render("police", 1.0, n=1).leds[0]
    assert a != b and a[0] > a[2] and b[2] > b[0]  # red, then blue


# --- breathe --------------------------------------------------------------------


def test_breathing_goes_from_the_floor_to_full_and_the_ring_grows():
    out, full = render("breathe", 0.0, color="#ffffff", floor=0.2), render("breathe", 2.0, color="#ffffff", floor=0.2)
    assert out.leds[0] == pytest.approx((0.2, 0.2, 0.2))
    assert full.leds[0] == pytest.approx((1, 1, 1))  # speed 0.25: full at 2 s
    assert m.lit(full.matrix) > m.lit(out.matrix)


# --- comet ----------------------------------------------------------------------


def test_the_comet_runs_in_its_direction():
    def brightest(**params):
        return [max(range(10), key=lambda i: luminance(render("comet", t, **params).leds[i])) for t in (0.2, 0.4, 0.6)]
    assert brightest() == sorted(brightest())  # to the right
    assert brightest(direction="left") == sorted(brightest(direction="left"), reverse=True)


def test_the_comets_head_is_white_and_its_tail_has_the_colour():
    p = render("comet", 0.3, color="#ff0000")
    lit = [c for c in p.leds if max(c) > 0]
    assert max(lit, key=luminance) == pytest.approx((1, 1, 1), abs=0.35)
    assert any(c[0] > 0.1 and c[1] < 0.05 for c in lit)  # red tail


def test_a_single_led_comet_blinks_once_a_pass():
    on = [level(render("comet", f / 30, n=1, speed=1.5)) > 0.3 for f in range(10 * 30)]
    assert sum(1 for a, b in zip(on, on[1:]) if b and not a) <= 15 + 1


# --- fire -----------------------------------------------------------------------


def test_fire_flickers_and_each_palette_has_its_colour():
    pictures = [render("fire", f / 30) for f in range(60)]
    assert len({p.leds for p in pictures}) > 50
    def mean(p, ch):
        return sum(c[ch] for c in p.leds) / len(p.leds)
    classic, blue, green = (render("fire", 1.0, palette=x) for x in ("classic", "blue", "green"))
    assert mean(classic, 0) > mean(classic, 2)  # red-orange
    assert mean(blue, 2) > mean(blue, 0)
    assert mean(green, 1) > mean(green, 0)


def test_calm_fire_hardly_flickers():
    pictures = [render("fire", f / 30, wildness=0.0) for f in range(60)]
    assert len({p.leds for p in pictures}) == 1


# --- solid ----------------------------------------------------------------------


def test_the_solid_drop_empties_and_fills_with_the_fade():
    params = {"fade": True, "fade_seconds": 2.0}
    full, empty = render("solid", 0.0, **params), render("solid", 2.0, **params)
    assert full.matrix == m.ICONS["drop"]
    assert m.lit(empty.matrix) < m.lit(full.matrix)
    assert render("solid", 1.3, fade=False).matrix == m.ICONS["drop"]


def test_the_rainbow_direction():
    rainbow = EFFECTS["rainbow"]()
    right = EFFECTS["rainbow"].defaults()
    left = right | {"direction": "left"}
    at = lambda params, t: rainbow.render(Context(led_count=10, t=t, params=params)).leds
    # moving right: what LED 0 shows now, LED 1 shows a little later
    t2 = (1 / 10) / right["speed"]  # the time the colours need to move one LED (width 1)
    assert at(right, 0)[0] == pytest.approx(at(right, t2)[1], abs=1e-9)
    assert at(left, 0)[1] == pytest.approx(at(left, t2)[0], abs=1e-9)


def test_solid_fades_between_the_two_colours():
    solid = EFFECTS["solid"]()
    params = EFFECTS["solid"].defaults() | {"fade": True, "color": "#000000", "color2": "#ffffff", "fade_seconds": 2.0}
    at = lambda t: solid.render(Context(led_count=3, t=t, params=params)).leds[0]
    assert at(0) == pytest.approx((0, 0, 0))
    assert at(1) == pytest.approx((0.5, 0.5, 0.5))
    assert at(2) == pytest.approx((1, 1, 1))
    assert at(4) == pytest.approx((0, 0, 0))
    without = params | {"fade": False}
    assert solid.render(Context(led_count=3, t=2, params=without)).leds[0] == (0, 0, 0)


def test_idle_is_calm():
    idle = EFFECTS["idle"]()
    pictures = [idle.render(Context(led_count=10, t=f / 30)) for f in range(12 * 30)]
    brightest = max(c for p in pictures for led in p.leds for c in led)
    assert brightest <= 0.56  # never more than about half
    assert {m.lit(p.matrix) for p in pictures} == {3}  # a dot with a tail
