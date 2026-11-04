"""Solid colour, optionally fading to a second colour and back (tech-spec 4.3).
The 8x8: a drop of paint, which empties and fills again with the fade."""

import math

from dod.engine.color import mix, parse_hex
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import ICONS, SIZE, from_pixels, is_on, outline, overlay
from dod.engine.picture import Picture


DROP_OUTLINE = outline(ICONS["drop"])


def drop(fill: float) -> bytes:
    """The drop's outline, filled from the bottom up to `fill` (0-1)."""
    top = SIZE - round(fill * SIZE)
    inside = from_pixels((x, y) for y in range(top, SIZE) for x in range(SIZE)
                         if is_on(ICONS["drop"], x, y))
    return overlay(DROP_OUTLINE, inside)


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
            matrix = drop(1 - f)  # full at the first colour, empty at the second
        else:
            color = a
            matrix = ICONS["drop"]
        return Picture(leds=[color] * ctx.led_count, matrix=matrix, matrix_brightness=0.5)
