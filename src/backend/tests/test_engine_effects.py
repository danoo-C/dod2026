"""Every effect, with every parameter at its extremes (docs/backend.md 12)."""

import math

import pytest

from dod.engine import matrix as m
from dod.engine.effects import EFFECTS
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


def test_the_rainbow_moves_and_its_matrix_never_flashes():
    rainbow = EFFECTS["rainbow"]()
    params = EFFECTS["rainbow"].defaults()
    pictures = [rainbow.render(Context(led_count=10, t=f / 30, params=params)) for f in range(90)]
    assert len({p.leds for p in pictures}) > 80  # changes every frame
    assert {m.lit(p.matrix) for p in pictures} == {32}
    assert len({p.matrix for p in pictures}) > 1  # the stripes move


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
