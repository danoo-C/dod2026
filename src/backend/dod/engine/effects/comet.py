"""Comet: a white head with a coloured tail runs along the strip, over and over
(tech-spec 4.3). The 8x8: a short comet along the diagonal.

The speed is passes a second, not LEDs a second, so a long strip doesn't make
it race and a single LED blinks at most 1.5 times a second.
"""

import math

from dod.engine.color import WHITE, mix, parse_hex, scale
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import from_pixels
from dod.engine.picture import Picture

GAP = 2  # dark LEDs after the tail, before the next pass
MATRIX_PATH = 12  # the diagonal is 8 pixels; 4 more so the tail leaves too


class Comet(Effect):
    id = "comet"
    name = "Kométa"
    params = (
        Param.color("color", "Farba", default="#38d4ff"),
        Param.slider("speed", "Rýchlosť", 0.2, 1.5, default=0.5, step=0.1),  # passes a second
        Param.slider("tail", "Dĺžka chvosta", 1.0, 6.0, default=3.0, step=1.0),  # LEDs
        Param.choice("direction", "Smer", [("right", "Doprava"), ("left", "Doľava")], default="right"),
    )

    def render(self, ctx: Context) -> Picture:
        p = ctx.params
        n, tail = ctx.led_count, p["tail"]
        color = parse_hex(p["color"])
        span = n + tail + GAP
        head = (ctx.t * p["speed"] % 1.0) * span  # from LED 0 past the end
        leds = []
        for i in range(n):
            behind = head - i  # how far the head is past this LED
            if behind < 0 or behind > tail + 1:
                leds.append((0.0, 0.0, 0.0))
            elif behind < 1:  # the head: white, fading into the tail colour
                leds.append(mix(WHITE, color, behind))
            else:
                leds.append(scale(color, (1 - (behind - 1) / (tail + 1)) ** 2))
        if p["direction"] == "left":
            leds.reverse()
        step = math.floor((ctx.t * p["speed"] % 1.0) * MATRIX_PATH)
        dots = [(q, q) for q in (step - k for k in range(4))]
        if p["direction"] == "left":
            dots = [(7 - x, y) for x, y in dots]
        return Picture(leds=leds, matrix=from_pixels(dots), matrix_brightness=0.6)
