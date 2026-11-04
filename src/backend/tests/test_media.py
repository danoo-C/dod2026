"""/media/<id>.mp4 and the music through the app (plan step 8): a short test
clip made with ffmpeg stands in for a song, nothing comes from YouTube."""

import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from hcl.testing import sim_link

from dod.control.sessions import INTERNAL_COOKIE, SESSION_COOKIE, new_token
from dod.engine import matrix as m
from dod.main import create_app
from dod.settings import Settings

SONG = "dQw4w9WgXcQ"
KEY = "test-key"


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """2 s of H.264 video and AAC audio, like a downloaded song."""
    path = tmp_path_factory.mktemp("clip") / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(path)],
        check=True, timeout=30)
    return path.read_bytes()


@pytest.fixture
def cache(tmp_path, clip):
    (tmp_path / f"{SONG}.mp4").write_bytes(clip)
    (tmp_path / f"{SONG}.json").write_text(json.dumps({"id": SONG, "title": "Never Gonna", "length": 2.0}))
    songs = tmp_path / "songs.txt"
    songs.write_text(f"https://youtu.be/{SONG}  Never Gonna\nhttps://youtu.be/y6120QOlsfU  Sandstorm\n")
    return tmp_path, songs


def app(cache, **kwargs):
    cache_dir, songs = cache
    link, board = sim_link()
    return create_app(Settings(internal_key=KEY, cache_dir=cache_dir), link=link, songs_file=songs, **kwargs), board


# --- /media -------------------------------------------------------------------


def test_a_song_is_served_whole(cache, clip):
    c = TestClient(app(cache)[0])
    r = c.get(f"/media/{SONG}.mp4")
    assert r.status_code == 200 and r.content == clip
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers.get("accept-ranges") == "bytes"


def test_range_requests_get_206(cache, clip):
    c = TestClient(app(cache)[0])
    r = c.get(f"/media/{SONG}.mp4", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.content == clip[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(clip)}"
    tail = c.get(f"/media/{SONG}.mp4", headers={"Range": "bytes=-50"})
    assert tail.status_code == 206 and tail.content == clip[-50:]


@pytest.mark.parametrize("path", [
    "/media/y6120QOlsfU.mp4",  # on the list, not downloaded
    "/media/9bZkp7q19f0.mp4",  # not on the list
    f"/media/{SONG}.json",
    f"/media/{SONG}",
    "/media/..%2F..%2Fetc%2Fpasswd.mp4",
    "/media/%2E%2E%2Fsongs.txt",
    f"/media/{SONG}.mp4.mp4",
])
def test_anything_else_is_404(cache, path):
    assert TestClient(app(cache)[0]).get(path).status_code == 404


def test_api_songs_lists_them_with_whats_downloaded(cache):
    with TestClient(app(cache)[0]) as c:
        assert c.get("/api/songs").json() == [
            {"id": SONG, "title": "Never Gonna", "length": 2.0, "ready": True},
            {"id": "y6120QOlsfU", "title": "Sandstorm", "length": None, "ready": False},
        ]


def test_a_bad_song_list_stops_the_backend_with_a_message(tmp_path, capsys):
    bad = tmp_path / "songs.txt"
    bad.write_text("https://vimeo.com/1  Nope\n")
    with pytest.raises(SystemExit):
        create_app(Settings(internal_key=KEY), link=sim_link()[0], songs_file=bad)
    assert "line 1: not a YouTube link" in capsys.readouterr().err


# --- the music through the WebSocket ------------------------------------------


def connect(client, role, key=None):
    cookie = f"{SESSION_COOKIE}={new_token()}" + (f"; {INTERNAL_COOKIE}={key}" if key else "")
    return client.websocket_connect(f"/ws?role={role}", headers={"cookie": cookie})


def until(ws, check, limit=600):
    for _ in range(limit):
        msg = ws.receive_json()
        if check(msg):
            return msg
    raise AssertionError("not seen")


def test_a_phone_without_a_main_screen_gets_no_player(cache):
    application, _ = app(cache)
    with TestClient(application) as c, connect(c, "phone") as phone:
        welcome = phone.receive_json()
        assert [s["ready"] for s in welcome["songs"]] == [True, False]
        phone.send_json({"type": "join_queue"})
        until(phone, lambda msg: msg["type"] == "you" and msg["in_control"])
        phone.send_json({"type": "play_song", "song": SONG})
        assert until(phone, lambda msg: msg["type"] == "error")["code"] == "no_player"


def test_the_spectrum_reaches_the_board_within_2_frames_and_fades_without_it(cache):
    application, board = app(cache)
    with TestClient(application) as c, connect(c, "main", KEY) as main:
        until(main, lambda msg: msg["type"] == "you")
        main.send_json({"type": "play_song", "song": SONG})
        until(main, lambda msg: msg["type"] == "state" and msg["mode"] == "music")
        loop = c.app.state.loop
        bands = [1.0] * 8 + [0.0] * 24  # loud lows: two full bars on the left
        want = m.bars(m.resample(bands, 8))
        ticks = loop.ticks
        main.send_json({"type": "spectrum", "bands": bands, "beat": False})
        deadline = time.monotonic() + 2
        while loop.last_output is None or loop.last_output.hardware.matrix != want:
            assert time.monotonic() < deadline, "the spectrum never showed"
            time.sleep(0.002)
        assert loop.ticks - ticks <= 2  # within 2 frames of arriving
        deadline = time.monotonic() + 2
        while board.picture is None or board.picture.matrix != want:  # and on the simulated board
            assert time.monotonic() < deadline, "not on the board"
            time.sleep(0.005)
        time.sleep(0.6)  # no spectrum for longer than 200 ms + the fade
        assert m.lit(loop.last_output.hardware.matrix) == 0
