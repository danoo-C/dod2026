"""Colour helpers for effects. Colours are (r, g, b) floats 0-1, as a person
sees them: gamma comes later, in output.py."""

from __future__ import annotations

import colorsys
import re

RGB = tuple[float, float, float]

BLACK: RGB = (0.0, 0.0, 0.0)
WHITE: RGB = (1.0, 1.0, 1.0)

HEX = re.compile(r"#[0-9a-fA-F]{6}")


def clamp01(v: float) -> float:
    """v limited to 0-1; NaN becomes 0."""
    if not v > 0.0:  # also catches NaN
        return 0.0
    return 1.0 if v > 1.0 else float(v)


def parse_hex(text: str) -> RGB:
    """'#ff8000' -> (1.0, 0.502, 0.0)"""
    if not HEX.fullmatch(text):
        raise ValueError(f"not a colour like #ff8000: {text!r}")
    return (int(text[1:3], 16) / 255, int(text[3:5], 16) / 255, int(text[5:7], 16) / 255)


def to_hex(rgb: tuple[int, int, int]) -> str:
    """(255, 128, 0) -> '#ff8000'"""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    """Hue wraps around (any float), saturation and value 0-1."""
    return colorsys.hsv_to_rgb(h % 1.0, s, v)


def mix(a: RGB, b: RGB, f: float) -> RGB:
    """a at f=0, b at f=1."""
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def scale(c: RGB, f: float) -> RGB:
    return (c[0] * f, c[1] * f, c[2] * f)


def luminance(c: RGB) -> float:
    """Perceived brightness 0-1 (Rec. 709 weights), used by the flash limit."""
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
