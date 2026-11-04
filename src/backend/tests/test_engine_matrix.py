"""8x8 and colour helpers."""

import math

import pytest

from dod.engine import matrix as m
from dod.engine.color import clamp01, hsv, luminance, mix, parse_hex, to_hex
from dod.engine.picture import Picture

HEART = (
    ".##..##.",
    "########",
    "########",
    "########",
    ".######.",
    "..####..",
    "...##...",
    "........",
)


def test_icon_round_trip_and_bit_order():
    bitmap = m.icon(*HEART)
    assert bitmap[0] == 0b01100110 and bitmap[7] == 0
    assert m.to_text(bitmap) == list(HEART)
    assert m.is_on(bitmap, 1, 0) and not m.is_on(bitmap, 0, 0)  # bit 7 is the leftmost pixel


@pytest.mark.parametrize("rows", [HEART[:7], HEART[:7] + ("#######",), HEART[:7] + ("..xx....",)])
def test_bad_icons(rows):
    with pytest.raises(ValueError):
        m.icon(*rows)


def test_lit_and_from_pixels():
    assert m.lit(m.BLANK) == 0 and m.lit(m.FULL) == 64
    bitmap = m.from_pixels([(0, 0), (7, 7), (8, 0), (-1, 3), (3, 9)])  # outside ones are left out
    assert m.lit(bitmap) == 2 and bitmap[0] == 0x80 and bitmap[7] == 0x01


def test_bars():
    assert m.to_text(m.bars([0, 0.125, 0.5, 1, 1.5, -1, math.nan, 0.99])) == [
        "...##..#",
        "...##..#",
        "...##..#",
        "...##..#",
        "..###..#",
        "..###..#",
        "..###..#",
        ".####..#",
    ]


def test_bars_from_32_bands():
    bands = [0.0] * 4 + [1.0] * 4 + [0.5] * 24
    text = m.to_text(m.bars(bands))
    assert [row[0] for row in text] == ["."] * 8  # first 4 bands -> column 0, all zero
    assert [row[1] for row in text] == ["#"] * 8  # next 4 -> column 1, full


def test_resample():
    assert m.resample([1, 2, 3, 4], 2) == [1.5, 3.5]
    assert m.resample([1, 2], 4) == [1, 1, 2, 2]
    assert m.resample([], 3) == [0.0, 0.0, 0.0]
    assert len(m.resample(list(range(32)), 8)) == 8


def test_border_goes_around_once():
    path = m.border()
    assert len(path) == 28 == len(set(path))
    assert path[0] == (0, 0) and path[7] == (7, 0) and path[14] == (7, 7) and path[21] == (0, 7)
    for (x1, y1), (x2, y2) in zip(path, path[1:] + path[:1]):
        assert abs(x1 - x2) + abs(y1 - y2) == 1  # neighbours, clockwise


def test_colours():
    assert parse_hex("#ff8000") == (1.0, 128 / 255, 0.0)
    assert to_hex((255, 128, 0)) == "#ff8000"
    with pytest.raises(ValueError):
        parse_hex("orange")
    assert clamp01(1.5) == 1.0 and clamp01(-1) == 0.0 and clamp01(math.nan) == 0.0
    assert mix((0, 0, 0), (1, 1, 1), 0.25) == (0.25, 0.25, 0.25)
    assert hsv(0) == (1, 0, 0) and hsv(1.0) == hsv(0.0) and hsv(-0.5) == hsv(0.5)
    assert luminance((1, 1, 1)) == pytest.approx(1.0) and luminance((0, 0, 1)) == pytest.approx(0.0722)


def test_picture_shape():
    p = Picture(leds=[[1, 0, 0]] * 3, matrix=bytearray(8), matrix_brightness=1)
    assert p.leds == ((1, 0, 0),) * 3 and p.matrix == bytes(8) and p.led_count == 3
    with pytest.raises(ValueError):
        Picture(leds=[(1, 0)])
    with pytest.raises(ValueError):
        Picture(leds=[(1, 0, 0)], matrix=bytes(7))
    assert Picture.black(4).leds == ((0.0, 0.0, 0.0),) * 4
