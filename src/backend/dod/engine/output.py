"""From Picture to what the LEDs and the pages get (docs/backend.md 7.3).

Always in this order:

1. master brightness
2. flash limit      - at most 3 flashes (6 transitions) in any second, strip and 8x8 separately
3. power limit      - the strip's estimated current stays under DOD_POWER_LIMIT_MA
4. preview          - the picture at this point goes to the pages (screens do their own gamma)
5. gamma            - 2.2, so fades look even on LEDs
6. integers         - 0-255 per channel, matrix brightness 0-15

OutputStage keeps the flash limit's history, so there is one per render loop.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from dod.engine.color import RGB, clamp01, luminance, to_hex
from dod.engine.matrix import BLANK, lit
from dod.engine.picture import Picture

GAMMA = 2.2
MA_PER_CHANNEL = 20.0  # current of one fully lit channel (WS2812B: ~20 mA per colour)
MATRIX_LEVELS = 15  # MAX7219 brightness 0-15

FLASH_STEP = 0.2  # a change of the level by this much is a transition
FLASH_TRANSITIONS = 6  # transitions allowed in any window (3 flashes)
FLASH_WINDOW = 1.0  # seconds

Ints = tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class HardwareFrame:
    """What the board gets: after gamma, as integers."""

    leds: Ints  # 0-255, RGB
    matrix: bytes  # 8 rows; all off when the brightness rounds to 0 (the MAX7219 is never fully dark)
    matrix_brightness: int  # 0-15

    @property
    def led_count(self) -> int:
        return len(self.leds)


@dataclass(frozen=True)
class PreviewFrame:
    """What the pages draw: the same picture before gamma, so a screen shows what a person sees."""

    leds: Ints  # 0-255, RGB
    matrix: bytes
    matrix_brightness: int  # 0-15

    def hex_leds(self) -> list[str]:
        return [to_hex(c) for c in self.leds]


@dataclass(frozen=True)
class Output:
    hardware: HardwareFrame
    preview: PreviewFrame
    strip_held: bool = False  # the flash limit repeated the previous strip
    matrix_held: bool = False  # ... or the previous 8x8
    power_scale: float = 1.0  # < 1 when the power limit dimmed the strip


class FlashLimiter:
    """Counts the transitions of one level (strip or 8x8) and says whether
    another one is allowed (docs/backend.md 7.3).

    A transition is a change of the level by at least FLASH_STEP from the last
    peak or low point. Between transitions, the running peak (after going up)
    or low point (after going down) follows the level.
    """

    def __init__(self, step: float = FLASH_STEP, limit: int = FLASH_TRANSITIONS,
                 window: float = FLASH_WINDOW) -> None:
        self.step = step
        self.limit = limit
        self.window = window
        self.reset()

    def reset(self) -> None:
        self._direction = 0  # +1 after an up transition, -1 after a down one, 0 before any
        self._low: float | None = None
        self._high: float | None = None
        self._times: deque[float] = deque()

    def transition(self, level: float) -> int:
        """+1 or -1 if showing `level` next would be a transition, else 0."""
        if self._low is None or self._high is None:
            return 0
        step = self.step - 1e-9  # a change of exactly `step` counts, despite float rounding (1.0 - 0.8)
        if self._direction >= 0 and self._high - level >= step:
            return -1
        if self._direction <= 0 and level - self._low >= step:
            return +1
        return 0

    def count(self, now: float) -> int:
        """Transitions in the window ending now."""
        while self._times and self._times[0] <= now - self.window:
            self._times.popleft()
        return len(self._times)

    def allowed(self, now: float) -> bool:
        """Whether one more transition fits into the window ending now."""
        return self.count(now) < self.limit

    def show(self, level: float, now: float) -> None:
        """`level` is shown now; record it."""
        if self._low is None or self._high is None:
            self._low = self._high = level
            return
        t = self.transition(level)
        if t:
            self._times.append(now)
            self._direction = t
            self._low = self._high = level
        else:
            self._low = min(self._low, level)
            self._high = max(self._high, level)


class OutputStage:
    def __init__(self, *, brightness: float, power_limit_ma: float) -> None:
        self.brightness = brightness
        if not power_limit_ma > 0:
            raise ValueError("power_limit_ma must be positive")
        self.power_limit_ma = power_limit_ma
        self._strip_flash = FlashLimiter()
        self._matrix_flash = FlashLimiter()
        self._last_leds: list[RGB] | None = None
        self._last_matrix: tuple[bytes, float] | None = None

    @property
    def brightness(self) -> float:
        return self._brightness

    @brightness.setter
    def brightness(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"brightness must be 0-1, got {value!r}")
        self._brightness = float(value)

    def reset(self) -> None:
        """Forget the history (a new board, a new LED count)."""
        self._strip_flash.reset()
        self._matrix_flash.reset()
        self._last_leds = None
        self._last_matrix = None

    def apply(self, picture: Picture, now: float) -> Output:
        """The picture through steps 1-6. `now` is a monotonic time in seconds."""
        b = self._brightness

        # 1. master brightness (and clamping whatever an effect got slightly wrong)
        leds = [(clamp01(r) * b, clamp01(g) * b, clamp01(bl) * b) for r, g, bl in picture.leds]
        matrix, matrix_b = picture.matrix, clamp01(picture.matrix_brightness) * b

        # 2. flash limit, strip and 8x8 separately
        if self._last_leds is not None and len(self._last_leds) != len(leds):
            self._strip_flash.reset()  # another LED count: the old picture can't be repeated
            self._last_leds = None
        strip_level = sum(luminance(c) for c in leds) / len(leds) if leds else 0.0
        strip_held = self._limit(self._strip_flash, strip_level, now, self._last_leds is not None)
        if strip_held:
            assert self._last_leds is not None
            leds = self._last_leds
        self._last_leds = leds

        matrix_level = lit(matrix) / 64 * matrix_b
        matrix_held = self._limit(self._matrix_flash, matrix_level, now, self._last_matrix is not None)
        if matrix_held:
            assert self._last_matrix is not None
            matrix, matrix_b = self._last_matrix
        self._last_matrix = (matrix, matrix_b)

        # 3. power limit, computed on what the LEDs really get (after gamma), applied before it
        current = MA_PER_CHANNEL * sum(c ** GAMMA for led in leds for c in led)
        scale = 1.0
        if current > self.power_limit_ma:
            scale = (self.power_limit_ma / current) ** (1 / GAMMA)
            leds = [(r * scale, g * scale, bl * scale) for r, g, bl in leds]

        # 4. preview: before gamma
        level = round(matrix_b * MATRIX_LEVELS)
        shown_matrix = matrix if level > 0 else BLANK
        preview = PreviewFrame(
            leds=tuple((round(r * 255), round(g * 255), round(bl * 255)) for r, g, bl in leds),
            matrix=shown_matrix,
            matrix_brightness=level,
        )

        # 5. + 6. gamma, integers. When the power limit is on, round down, so the
        # integers can't add up to more than the limit.
        to_int = math.floor if scale < 1.0 else round
        hardware = HardwareFrame(
            leds=tuple((to_int(r ** GAMMA * 255), to_int(g ** GAMMA * 255), to_int(bl ** GAMMA * 255))
                       for r, g, bl in leds),
            matrix=shown_matrix,
            matrix_brightness=level,
        )
        return Output(hardware=hardware, preview=preview, strip_held=strip_held, matrix_held=matrix_held,
                      power_scale=scale)

    @staticmethod
    def _limit(flash: FlashLimiter, level: float, now: float, can_hold: bool) -> bool:
        """True if the previous picture must be repeated instead of this one."""
        if can_hold and flash.transition(level) and not flash.allowed(now):
            return True
        flash.show(level, now)
        return False


def estimated_current_ma(frame: HardwareFrame) -> float:
    """The strip's current for a finished frame, the way the power limit counts it."""
    return MA_PER_CHANNEL * sum(c for led in frame.leds for c in led) / 255
