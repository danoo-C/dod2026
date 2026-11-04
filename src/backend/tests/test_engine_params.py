"""Param and Effect declarations (docs/backend.md 7.2)."""

import json
import math

import pytest

from dod.engine.effects import EFFECTS, PRESETS
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.picture import Picture


# --- Param ----------------------------------------------------------------------


def test_slider():
    p = Param.slider("speed", "Rýchlosť", 0.2, 3.0, default=1.0, step=0.1)
    assert p.check(2) == 2.0 and isinstance(p.check(2), float)
    assert p.check(0.2) == 0.2 and p.check(3.0) == 3.0
    for bad in (0.1, 3.01, math.nan, math.inf, "1", None, True):
        with pytest.raises(ValueError):
            p.check(bad)
    assert p.samples() == [0.2, 3.0, 1.0]
    assert p.describe() == {"name": "speed", "label": "Rýchlosť", "kind": "slider", "default": 1.0,
                            "min": 0.2, "max": 3.0, "step": 0.1}


def test_color():
    p = Param.color("color", "Farba", default="#FF0000")
    assert p.default == "#ff0000"
    assert p.check("#00Ff80") == "#00ff80"
    for bad in ("red", "#fff", "ff0000", "#ff00000", "#gg0000", 0xFF0000, None):
        with pytest.raises(ValueError):
            p.check(bad)
    assert p.samples() == ["#ff0000", "#000000", "#ffffff"]


def test_choice():
    p = Param.choice("direction", "Smer", [("right", "Doprava"), ("left", "Doľava")], default="left")
    assert p.check("right") == "right"
    for bad in ("up", "Doprava", None, 1):
        with pytest.raises(ValueError):
            p.check(bad)
    assert p.samples() == ["right", "left"]
    assert p.describe()["options"] == [{"value": "right", "label": "Doprava"}, {"value": "left", "label": "Doľava"}]


def test_toggle():
    p = Param.toggle("fade", "Prelínanie")
    assert p.default is False and p.check(True) is True
    for bad in (1, 0, "true", None):
        with pytest.raises(ValueError):
            p.check(bad)
    assert p.samples() == [False, True]


@pytest.mark.parametrize("make", [
    lambda: Param.slider("s", "S", 1, 1, default=1),                       # min == max
    lambda: Param.slider("s", "S", 0, 1, default=2),                       # default out of range
    lambda: Param.color("c", "C", default="red"),
    lambda: Param.choice("c", "C", [], default="a"),
    lambda: Param.choice("c", "C", [("a", "A"), ("a", "B")], default="a"),  # a value twice
    lambda: Param.choice("c", "C", [("a", "A")], default="b"),
    lambda: Param.toggle("t", "T", default=1),                             # type: ignore[arg-type]
    lambda: Param.toggle("not a name", "T"),
])
def test_bad_declarations_fail_at_once(make):
    with pytest.raises(ValueError):
        make()


# --- Effect ---------------------------------------------------------------------


def test_an_effect_needs_an_id_and_a_name():
    with pytest.raises(TypeError, match="'id'"):
        class NoId(Effect):
            name = "X"
    with pytest.raises(TypeError, match="'name'"):
        class NoName(Effect):
            id = "x"


def test_an_effect_declares_each_parameter_once():
    with pytest.raises(TypeError, match="twice"):
        class Twice(Effect):
            id = "twice"
            name = "Dvakrát"
            params = (Param.toggle("a", "A"), Param.toggle("a", "B"))


def test_check_param():
    class Demo(Effect):
        id = "demo"
        name = "Demo"
        params = (Param.slider("speed", "Rýchlosť", 0, 1, default=0.5),)

        def render(self, ctx: Context) -> Picture:
            return Picture.black(ctx.led_count)

    assert Demo.check_param("speed", 1) == 1.0
    with pytest.raises(ValueError, match="no parameter"):
        Demo.check_param("height", 1)
    with pytest.raises(ValueError):
        Demo.check_param("speed", 2)
    assert Demo.defaults() == {"speed": 0.5}


# --- the registry ---------------------------------------------------------------


def test_the_registry():
    assert list(EFFECTS) == ["rainbow", "fire", "police", "breathe", "comet", "strobe", "solid", "idle"]
    assert list(PRESETS) == ["rainbow", "fire", "police", "breathe", "comet", "strobe", "solid"]  # idle can't be picked
    for effect_id, effect in EFFECTS.items():
        assert effect.id == effect_id and effect.name


def test_descriptions_are_json_for_the_phone():
    text = json.dumps([e.describe() for e in PRESETS.values()], ensure_ascii=False)
    assert '"Rýchlosť"' in text
    for e in PRESETS.values():
        assert [p["name"] for p in e.describe()["params"]] == [p.name for p in e.params]
