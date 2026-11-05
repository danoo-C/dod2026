"""Each song's light show worked out ahead (dod/music/timeline.py): the same
spectrum as the browser, through the backend's own show, into a picture."""

import json
import re
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pytest

from dod.engine.effects import music as mu
from dod.music import timeline as tl
from dod.music.library import Library, Song

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "apps" / "Music"
SONG = "dQw4w9WgXcQ"


def ts_constants(name):
    text = (FRONTEND / name).read_text(encoding="utf-8")
    return {k: float(v) for k, v in re.findall(r"export const (\w+) = (-?[\d.]+);", text)}


def test_the_copied_constants_match_the_frontend():
    # timeline.py repeats what the browser does; if the frontend changes, so must it
    spectrum, beat = ts_constants("spectrum.ts"), ts_constants("beat.ts")
    for name in ("BANDS", "LOW_HZ", "HIGH_HZ", "MIN_DB", "MAX_DB", "TILT_DB_PER_OCTAVE", "PIVOT_HZ", "WINDOW_DB",
                 "CURVE", "PEAK_FALL_DB", "PEAK_FLOOR_DB"):
        assert getattr(tl, name) == spectrum[name], name
    for name in ("LOW_BANDS", "WINDOW", "K", "MIN_FLUX_DB", "GAP"):
        assert getattr(tl, name) == beat[name], name
    graph = (FRONTEND / "audioGraph.ts").read_text(encoding="utf-8")
    assert f"FFT_SIZE = {tl.FFT_SIZE};" in graph
    assert f"smoothingTimeConstant = {tl.SMOOTHING};" in graph
    player = (FRONTEND / "Player.tsx").read_text(encoding="utf-8")
    assert f"SPECTRUM_MS = 1000 / {tl.FPS};" in player


def test_the_bands_are_contiguous_and_logarithmic():
    edges = tl.band_edges()
    assert len(edges) == tl.BANDS and edges[0][0] == 1  # bin 0 is DC
    assert all(b[0] == a[1] + 1 for a, b in zip(edges, edges[1:]))
    assert edges[-1][1] - edges[-1][0] > 10 * (edges[0][1] - edges[0][0])


def test_a_tone_lights_its_band():
    t = np.arange(tl.SAMPLE_RATE * 2) / tl.SAMPLE_RATE
    bands = tl.raw_bands((0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32))
    centres = tl.LOW_HZ * (tl.HIGH_HZ / tl.LOW_HZ) ** ((np.arange(tl.BANDS) + 0.5) / tl.BANDS)
    assert int(np.argmax(bands[-1])) == int(np.argmin(abs(centres - 1000)))
    assert bands[0].max() == 0  # the first frame ends at the first sample: silence


@pytest.fixture(scope="module")
def kicks(tmp_path_factory):
    """6 s of a 120 BPM kick drum (a decaying 55 Hz tone) over quiet noise, as an .mp4."""
    path = tmp_path_factory.mktemp("kicks") / "kicks.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:size=64x48:rate=5:duration=6",
         "-f", "lavfi", "-i", "aevalsrc=0.8*sin(2*PI*55*t)*exp(-25*mod(t\\,0.5))+0.01*(random(0)-0.5):d=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True, timeout=30)
    return path


def test_the_kicks_of_a_song_are_found(kicks):
    frames = tl.spectra(tl.decode(kicks))
    assert len(frames) == pytest.approx(6 * tl.FPS, abs=3)
    beats = [i / tl.FPS for i, (_, beat) in enumerate(frames) if beat]
    assert 10 <= len(beats) <= 12  # one every 0.5 s
    assert all(0.45 <= b - a <= 0.55 for a, b in zip(beats, beats[1:]))
    assert all(len(bands) == tl.BANDS and all(0 <= v <= 1 for v in bands) for bands, _ in frames)


def test_the_show_is_the_effects_own():
    frames = [([0.6] * 32, i % 15 == 0) for i in range(60)]
    show = tl.show(frames)
    assert len(show.leds) == 60 and all(len(f) == 10 for f in show.leds)
    assert show.kicks == 4
    assert all(0 <= v <= 255 for f in show.leds for c in f for v in c)
    assert show.leds[0] != show.leds[30]  # it moves


def png_size(data):
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def png_pixel(data, x, y):
    width, _ = png_size(data)
    raw = zlib.decompress(data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8])
    row = raw[y * (width * 3 + 1) + 1:(y + 1) * (width * 3 + 1)]
    return tuple(row[x * 3:x * 3 + 3])


def test_the_picture_one_column_per_frame_one_band_per_led():
    leds = [tuple((10 * j, i, 200) for j in range(10)) for i in range(5)]
    data = tl.png(leds)
    assert png_size(data) == (5, 10 * tl.LED_PX + 9 * tl.GAP_PX)
    assert png_pixel(data, 3, 0) == (0, 3, 200)  # LED 0, frame 3
    assert png_pixel(data, 2, tl.LED_PX) == tl.BACKGROUND  # the gap
    assert png_pixel(data, 4, tl.LED_PX + tl.GAP_PX) == (10, 4, 200)  # LED 1


def test_make_writes_the_picture_and_its_version(kicks, tmp_path, monkeypatch):
    show = tl.make(kicks, tmp_path, SONG)
    picture, meta = tl.files(tmp_path, SONG)
    assert png_size(picture.read_bytes())[0] == len(show.leds)
    data = json.loads(meta.read_text())
    assert data["version"] == tl.VERSION and data["fps"] == tl.FPS and data["kicks"] == show.kicks >= 10
    assert tl.current(tmp_path, SONG)
    monkeypatch.setattr(tl, "VERSION", "another-show")
    assert not tl.current(tmp_path, SONG)  # the show changed: stale


def test_the_version_follows_the_shows_code():
    assert re.fullmatch(r"[0-9a-f]{16}", tl.VERSION)
    assert tl._version() == tl.VERSION
    assert Path(mu.__file__).name == "music.py" and "engine/effects/music.py" in tl.SOURCES


def test_refresh_makes_only_the_missing_ones_and_names_the_failures(kicks, tmp_path):
    said = []
    assert tl.refresh(tmp_path, [(SONG, kicks)], said.append) == []
    assert any("done" in s for s in said)
    said.clear()
    assert tl.refresh(tmp_path, [(SONG, kicks)], said.append) == []
    assert said == []  # current: nothing to do
    assert tl.refresh(tmp_path, [("y6120QOlsfU", tmp_path / "missing.mp4")], said.append) == ["y6120QOlsfU"]
    assert not tl.current(tmp_path, "y6120QOlsfU")


def test_the_library_serves_only_current_pictures_of_listed_songs(kicks, tmp_path, monkeypatch):
    (tmp_path / f"{SONG}.mp4").write_bytes(kicks.read_bytes())
    (tmp_path / f"{SONG}.json").write_text(json.dumps({"id": SONG, "title": "Rick", "length": 6.0}))
    library = Library([Song(SONG, "Rick"), Song("y6120QOlsfU", "Sandstorm")], tmp_path)
    assert library.show(SONG) is None  # not made
    tl.make(tmp_path / f"{SONG}.mp4", tmp_path, SONG)
    assert library.show(SONG) == tl.files(tmp_path, SONG)[0]
    assert library.show("y6120QOlsfU") is None and library.show("../etc/passwd") is None
    monkeypatch.setattr(tl, "VERSION", "another-show")
    assert library.show(SONG) is None
