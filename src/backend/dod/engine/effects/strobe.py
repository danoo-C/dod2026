"""Strobe: short flashes of the whole strip (tech-spec 4.3). The 8x8: a
lightning bolt, the whole matrix lit with every flash.

Photosensitive epilepsy: the output stage allows at most 3 flashes a second
(backend.md 7.3) as a safety net, and this preset stays under it on its own –
at most 2 flashes a second, so the limit never has to step in (plan step 7).
"""

from dod.engine.color import parse_hex
from dod.engine.effects.base import Context, Effect, Param
from dod.engine.matrix import FULL, ICONS
from dod.engine.picture import Picture

MAX_RATE = 2.0  # flashes a second; the flash limit is 3
FLASH_SECONDS = 0.1  # 3 frames at 30 fps: long enough to see, short enough to be a flash


class Strobe(Effect):
    id = "strobe"
    name = "Stroboskop"
    params = (
        Param.slider("rate", "Záblesky za sekundu", 0.5, MAX_RATE, default=1.0, step=0.1),
        Param.color("color", "Farba", default="#ffffff"),
    )

    def render(self, ctx: Context) -> Picture:
        p = ctx.params
        since = ctx.t % (1.0 / p["rate"])  # seconds since this period's flash began
        on = since < FLASH_SECONDS
        color = parse_hex(p["color"]) if on else (0.0, 0.0, 0.0)
        return Picture(leds=[color] * ctx.led_count, matrix=FULL if on else ICONS["lightning"],
                       matrix_brightness=0.6)
