"""Solid colour, optionally fading to a second colour and back (tech-spec 4.3)."""

import math

from dod.engine.color import mix, parse_hex
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import ICONS
from dod.engine.picture import Picture


class Solid(Effect):
    id = "solid"
    name = "Farba"
    params = (
        Param.color("color", "Farba", default="#ff2a6d"),
        Param.toggle("fade", "Prelínanie", default=False),
        Param.color("color2", "Druhá farba", default="#05d9e8"),
        Param.slider("fade_seconds", "Dĺžka prelínania (s)", 0.5, 10.0, default=3.0, step=0.5),
    )

    def render(self, ctx: Context) -> Picture:
        a = parse_hex(ctx.params["color"])
        if ctx.params["fade"]:
            # a -> color2 in fade_seconds, and back, with a soft (cosine) curve
            f = (1 - math.cos(math.pi * ctx.t / ctx.params["fade_seconds"])) / 2
            color = mix(a, parse_hex(ctx.params["color2"]), f)
        else:
            color = a
        # the 8x8 until step 7 decides: a frame
        return Picture(leds=[color] * ctx.led_count, matrix=ICONS["square"], matrix_brightness=0.5)
