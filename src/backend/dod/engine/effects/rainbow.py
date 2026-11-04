"""A rainbow moving along the strip. The 8x8: a rainbow's arc."""

from dod.engine.color import hsv
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import ICONS
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
        return Picture(leds=leds, matrix=ICONS["rainbow"], matrix_brightness=0.6)
