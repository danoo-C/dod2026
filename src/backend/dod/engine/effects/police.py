"""Police lights: the strip's two halves take turns (tech-spec 4.3). The 8x8:
a block switching sides with them.

No strobing: a half is either on or dimmed, and they swap at most twice a
second. With red and blue, the strip's average brightness stays almost the
same whichever half is on, so it never counts as a flash.
"""

import math

from dod.engine.color import scale
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import from_pixels
from dod.engine.picture import Picture

COLOURS = {
    "redblue": ((1.0, 0.04, 0.12), (0.10, 0.25, 1.0)),
    "amber": ((1.0, 0.45, 0.0), (1.0, 0.45, 0.0)),  # a tow truck
}
DIM = 0.06  # the half that is off still glows a little


class Police(Effect):
    id = "police"
    name = "Polícia"
    params = (
        Param.slider("speed", "Rýchlosť", 0.5, 2.0, default=1.0, step=0.1),  # swaps a second
        Param.choice("colours", "Farby", [("redblue", "Červená a modrá"), ("amber", "Oranžová")],
                     default="redblue"),
    )

    def render(self, ctx: Context) -> Picture:
        p = ctx.params
        right = math.floor(ctx.t * p["speed"]) % 2 == 1
        a, b = COLOURS[p["colours"]]
        n = ctx.led_count
        half = n // 2 if n > 1 else 1  # a single LED takes both turns
        leds = []
        for i in range(n):
            on_left = i < half
            if n == 1:
                leds.append(b if right else a)
            elif on_left:
                leds.append(scale(a, DIM if right else 1.0))
            else:
                leds.append(scale(b, 1.0 if right else DIM))
        x0 = 4 if right else 0
        block = from_pixels((x, y) for y in range(1, 7) for x in range(x0, x0 + 4))
        return Picture(leds=leds, matrix=block, matrix_brightness=0.6)
