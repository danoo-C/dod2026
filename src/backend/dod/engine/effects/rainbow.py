"""A rainbow moving along the strip."""

import math

from dod.engine.color import hsv
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import from_pixels
from dod.engine.picture import Picture


class Rainbow(Effect):
    id = "rainbow"
    name = "Dúha"
    params = (
        Param.slider("speed", "Rýchlosť", 0.05, 2.0, default=0.3, step=0.05),  # turns of the colour wheel per second
        Param.slider("width", "Počet dúh", 0.25, 3.0, default=1.0, step=0.25),  # rainbows along the strip
        Param.slider("saturation", "Sýtosť", 0.0, 1.0, default=1.0, step=0.05),
        Param.choice("direction", "Smer", [("right", "Doprava"), ("left", "Doľava")], default="right"),
    )

    def render(self, ctx: Context) -> Picture:
        p = ctx.params
        sign = 1.0 if p["direction"] == "right" else -1.0
        shift = ctx.t * p["speed"]
        n = ctx.led_count
        leds = [hsv(p["width"] * i / n - sign * shift, p["saturation"], 1.0) for i in range(n)]
        # the 8x8 until step 7 decides: diagonal stripes moving with the colours
        # (always 32 pixels on, so the 8x8 never flashes)
        step = math.floor(shift * 8)
        pixels = [(x, y) for x in range(8) for y in range(8) if (x + y - sign * step) % 4 < 2]
        return Picture(leds=leds, matrix=from_pixels(pixels), matrix_brightness=0.6)
