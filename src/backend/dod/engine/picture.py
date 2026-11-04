"""Picture: what an effect produces (docs/backend.md 7.3)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from dod.engine.color import RGB

MATRIX_ROWS = 8


@dataclass(frozen=True, init=False)
class Picture:
    """One moment of the show, before any limits.

    leds               per LED (r, g, b), floats 0-1, as a person should see them
    matrix             8 row bytes, row 0 = top, bit 7 = leftmost pixel
    matrix_brightness  0-1, for the whole 8x8 (it has only one setting)

    Colours outside 0-1 (rounding in an effect) are clamped by output.py, not
    rejected here; a wrong shape is always a bug and raises ValueError.
    """

    leds: tuple[RGB, ...]
    matrix: bytes = bytes(MATRIX_ROWS)
    matrix_brightness: float = 0.0

    def __init__(self, leds: Iterable[RGB], matrix: bytes = bytes(MATRIX_ROWS),
                 matrix_brightness: float = 0.0) -> None:
        leds = tuple(tuple(c) for c in leds)
        for i, c in enumerate(leds):
            if len(c) != 3:
                raise ValueError(f"LED {i} must be (r, g, b), got {c!r}")
        matrix = bytes(matrix)
        if len(matrix) != MATRIX_ROWS:
            raise ValueError(f"matrix must be {MATRIX_ROWS} rows, got {len(matrix)}")
        object.__setattr__(self, "leds", leds)
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "matrix_brightness", float(matrix_brightness))

    @property
    def led_count(self) -> int:
        return len(self.leds)

    @classmethod
    def black(cls, led_count: int) -> Picture:
        """Everything off."""
        return cls(leds=[(0.0, 0.0, 0.0)] * led_count)
