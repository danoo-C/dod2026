"""Breathing: the whole strip fades in and out, slowly (tech-spec 4.3). The
8x8: a ring growing and shrinking with it.

At most 0.8 breaths a second: one breath is one way up and one way down, so
even at full speed it stays far under the flash limit's 3 flashes a second.
"""

import math

from dod.engine.color import parse_hex, scale
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import ring
from dod.engine.picture import Picture


class Breathe(Effect):
    id = "breathe"
    name = "Dýchanie"
    params = (
        Param.color("color", "Farba", default="#ff4d8d"),
        Param.slider("speed", "Rýchlosť", 0.1, 0.8, default=0.25, step=0.05),  # breaths a second
        Param.slider("floor", "Najnižší jas", 0.0, 0.5, default=0.1, step=0.05),
    )

    def render(self, ctx: Context) -> Picture:
        p = ctx.params
        breath = (1 - math.cos(2 * math.pi * ctx.t * p["speed"])) / 2  # 0 -> 1 -> 0
        level = p["floor"] + (1 - p["floor"]) * breath
        color = scale(parse_hex(p["color"]), level)
        return Picture(leds=[color] * ctx.led_count, matrix=ring(0.6 + 3.0 * breath), matrix_brightness=0.6)
