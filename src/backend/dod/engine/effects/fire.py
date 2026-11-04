"""Fire: every LED flickers on its own, between ember and flame (tech-spec 4.3).
The 8x8: a flame with sparks flickering above it.

Deterministic like every effect: the flicker is a sum of sines with a phase
per LED, not random numbers, so the same moment always looks the same. The
strip's average hardly moves (the LEDs flicker out of step), so it never
comes near the flash limit.
"""

import math

from dod.engine.color import clamp01, hsv
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import ICONS, from_pixels, overlay
from dod.engine.picture import Picture

# (hue of the embers, hue of the hottest flame) per palette
PALETTES = {
    "classic": (0.0, 0.11),  # deep red to yellow-orange
    "blue": (0.66, 0.53),  # deep blue to cyan, a gas flame
    "green": (0.38, 0.22),  # green to lime, a chemistry show
}


class Fire(Effect):
    id = "fire"
    name = "Oheň"
    params = (
        Param.slider("speed", "Rýchlosť", 0.3, 2.0, default=1.0, step=0.1),
        Param.slider("wildness", "Divokosť", 0.0, 1.0, default=0.6, step=0.05),
        Param.choice("palette", "Plameň", [("classic", "Oheň"), ("blue", "Modrý"), ("green", "Zelený")],
                     default="classic"),
    )

    def render(self, ctx: Context) -> Picture:
        p = ctx.params
        tt = ctx.t * p["speed"]
        cold, hot = PALETTES[p["palette"]]
        leds = []
        for i in range(ctx.led_count):
            wobble = 0.25 * math.sin(tt * 7 + i * 2.1) + 0.15 * math.sin(tt * 13.3 + i * 5.7)
            heat = clamp01(0.62 + p["wildness"] * wobble)
            leds.append(hsv(cold + (hot - cold) * heat * heat, 1.0, 0.35 + 0.65 * heat))
        # sparks: one row above the flame's shoulders, each column on its own rhythm
        sparks = from_pixels((x, 1) for x in range(8) if math.sin(tt * 9 + x * 2.3) > 0.55)
        return Picture(leds=leds, matrix=overlay(ICONS["flame"], sparks), matrix_brightness=0.55)
