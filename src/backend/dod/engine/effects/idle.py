"""When nobody plays (docs/backend.md 6): calm colours drifting along the strip,
gently breathing, and a dot circling the 8x8's edge. Phones can't pick it."""

import math

from dod.engine.color import hsv
from dod.engine.effects.base import Context, Effect
from dod.engine.matrix import border, from_pixels
from dod.engine.picture import Picture

BREATH_SECONDS = 6.0  # one breath in and out
HUE_SECONDS = 40.0  # once around the colour wheel
DOT_STEP_SECONDS = 0.15  # the dot moves one pixel
TAIL = 2  # pixels behind the dot


class Idle(Effect):
    id = "idle"
    name = "Čakanie"
    pickable = False

    def render(self, ctx: Context) -> Picture:
        breath = (1 - math.cos(2 * math.pi * ctx.t / BREATH_SECONDS)) / 2  # 0-1
        value = 0.25 + 0.3 * breath
        base = ctx.t / HUE_SECONDS
        n = ctx.led_count
        leds = [hsv(base + 0.3 * i / n, 0.6, value) for i in range(n)]
        path = border()
        head = math.floor(ctx.t / DOT_STEP_SECONDS)
        dots = [path[(head - k) % len(path)] for k in range(TAIL + 1)]
        return Picture(leds=leds, matrix=from_pixels(dots), matrix_brightness=0.4)
