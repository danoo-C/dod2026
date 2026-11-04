"""Helpers for the 8x8 (docs/backend.md 7.4): single colour, every pixel on or
off. A matrix is 8 row bytes, row 0 = top, bit 7 = the leftmost pixel.

The icons and animations per preset are decided in step 7 (tech-spec 5.3);
the ones here are what the first effects need.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

SIZE = 8
BLANK = bytes(SIZE)
FULL = bytes([0xFF] * SIZE)


def icon(*rows: str) -> bytes:
    """A bitmap from 8 strings of 8 characters, '#' on and '.' off:

        icon("..####..", ".#....#.", ...)
    """
    if len(rows) != SIZE:
        raise ValueError(f"an icon has {SIZE} rows, got {len(rows)}")
    out = bytearray()
    for y, row in enumerate(rows):
        if len(row) != SIZE or set(row) - {"#", "."}:
            raise ValueError(f"row {y} must be 8 of '#' and '.', got {row!r}")
        out.append(sum(0x80 >> x for x, ch in enumerate(row) if ch == "#"))
    return bytes(out)


def from_pixels(pixels: Iterable[tuple[int, int]]) -> bytes:
    """A bitmap with the given (x, y) pixels on; pixels outside the 8x8 are left out."""
    rows = bytearray(SIZE)
    for x, y in pixels:
        if 0 <= x < SIZE and 0 <= y < SIZE:
            rows[y] |= 0x80 >> x
    return bytes(rows)


def is_on(matrix: bytes, x: int, y: int) -> bool:
    return bool(matrix[y] & (0x80 >> x))


def lit(matrix: bytes) -> int:
    """How many pixels are on, 0-64."""
    return sum(row.bit_count() for row in matrix)


def to_text(matrix: bytes) -> list[str]:
    """The opposite of icon(), for tests and debugging."""
    return ["".join("#" if row & (0x80 >> x) else "." for x in range(SIZE)) for row in matrix]


def resample(values: Sequence[float], n: int) -> list[float]:
    """`values` squeezed or stretched to `n` values: each output is the average of
    its share of the input (32 bands -> 8 bars)."""
    if not values:
        return [0.0] * n
    size = len(values)
    out = []
    for i in range(n):
        lo = i * size // n
        hi = max((i + 1) * size // n, lo + 1)
        part = values[lo:hi]
        out.append(sum(part) / len(part))
    return out


def bars(values: Sequence[float]) -> bytes:
    """8 columns growing from the bottom; each value 0-1 is a column's height.
    Other counts are resampled to 8 first."""
    if len(values) != SIZE:
        values = resample(values, SIZE)
    rows = bytearray(SIZE)
    for x, v in enumerate(values):
        height = round(min(max(v, 0.0), 1.0) * SIZE) if v == v else 0  # NaN -> 0
        for y in range(SIZE - height, SIZE):
            rows[y] |= 0x80 >> x
    return bytes(rows)


def border() -> list[tuple[int, int]]:
    """The 28 pixels around the edge, clockwise from the top left."""
    top = [(x, 0) for x in range(SIZE)]
    right = [(SIZE - 1, y) for y in range(1, SIZE)]
    bottom = [(x, SIZE - 1) for x in range(SIZE - 2, -1, -1)]
    left = [(0, y) for y in range(SIZE - 2, 0, -1)]
    return top + right + bottom + left


ICONS: dict[str, bytes] = {
    "square": icon(
        "........",
        ".######.",
        ".#....#.",
        ".#....#.",
        ".#....#.",
        ".#....#.",
        ".######.",
        "........",
    ),
}
