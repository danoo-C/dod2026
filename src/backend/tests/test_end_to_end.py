"""The whole stand once, end to end (plan step 10): the app with the simulated
board, a main screen, two phones and a logging page, through a round of the
day – queueing, a turn, presets on the board, a song with its spectrum, the
song ending and the turn passing on, the fake logs."""

import json
import time

from fastapi.testclient import TestClient
from hcl.testing import sim_link

from dod.control.sessions import INTERNAL_COOKIE, SESSION_COOKIE, new_token
from dod.engine import matrix as m
from dod.main import create_app
from dod.settings import Settings

SONG = "dQw4w9WgXcQ"
KEY = "e2e-key"


class Browser:
    """One WebSocket and everything it was sent, so the test can ask "has it seen…"."""

    def __init__(self, client, role, key=None):
        cookie = f"{SESSION_COOKIE}={new_token()}" + (f"; {INTERNAL_COOKIE}={key}" if key else "")
        self._cm = client.websocket_connect(f"/ws?role={role}", headers={"cookie": cookie})
        self.ws = self._cm.__enter__()
        self.seen = []
        self.welcome = self.next("welcome")

    def close(self):
        self._cm.__exit__(None, None, None)

    def send(self, **msg):
        self.ws.send_text(json.dumps(msg))

    def next(self, kind, check=lambda msg: True, limit=1000):
        """Reads until a `kind` message passing `check` (previews keep coming, so this never hangs)."""
        for _ in range(limit):
            msg = self.ws.receive_json()
            self.seen.append(msg)
            if msg["type"] == kind and check(msg):
                return msg
        raise AssertionError(f"no {kind} message")


def wait(cond, what, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, f"timed out: {what}"
        time.sleep(0.005)


def test_a_round_of_the_day(tmp_path):
    (tmp_path / f"{SONG}.mp4").write_bytes(b"\x00" * 64)
    (tmp_path / f"{SONG}.json").write_text(json.dumps({"id": SONG, "title": "Never Gonna", "length": 20.0}))
    songs = tmp_path / "songs.txt"
    songs.write_text(f"https://youtu.be/{SONG}  Never Gonna\n")
    link, board = sim_link()
    app = create_app(Settings(internal_key=KEY, cache_dir=tmp_path), link=link, songs_file=songs)

    with TestClient(app) as client:
        loop, state = client.app.state.loop, client.app.state.state
        wait(lambda: board.picture is not None, "the board's first frame")
        assert state.mode == "idle" and loop.scene.effect.id == "idle"

        main = Browser(client, "main", KEY)
        logging_page = Browser(client, "logging", KEY)
        anna, ben = Browser(client, "phone"), Browser(client, "phone")
        assert main.welcome["role"] == "main" and [s["ready"] for s in anna.welcome["songs"]] == [True]

        # queueing: Anna first gets control, Ben waits behind her
        anna.send(type="join_queue")
        anna.next("you", lambda y: y["in_control"])
        ben.send(type="join_queue")
        assert ben.next("you", lambda y: y["position"] == 1)["in_control"] is False

        # Ben can't control; Anna's preset and parameter reach the board
        ben.send(type="set_preset", preset="fire")
        assert ben.next("error")["code"] == "not_your_turn"
        anna.send(type="set_preset", preset="solid")
        anna.send(type="set_param", name="color", value="#00ff00")
        anna.next("state", lambda s: s["manual"]["preset"] == "solid" and s["manual"]["params"]["color"] == "#00ff00")
        wait(lambda: board.strip_rgb() is not None and all(board.strip_rgb()[i * 3 + 1] > 150 and board.strip_rgb()[i * 3] < 20
                                                           for i in range(10)), "green on the board")
        anna.send(type="set_matrix", mode="drawing", drawing="183c7effff7e3c18")
        wait(lambda: board.picture.matrix == bytes.fromhex("183c7effff7e3c18"), "the drawing on the board")

        # a song: the main screen plays it, its spectrum drives the 8x8
        anna.send(type="loading_started")
        anna.send(type="play_song", song=SONG)
        main.next("state", lambda s: s["mode"] == "music" and s["music"]["song"] == SONG)
        assert loop.scene.effect.id == "music"
        bands = [1.0] * 8 + [0.0] * 24
        for _ in range(3):
            main.send(type="spectrum", bands=bands, beat=True)
            main.send(type="player", song=SONG, position=1.0, ended=False)
        wait(lambda: board.picture.matrix == m.bars(m.resample(bands, 8)), "the spectrum on the board")

        # the song ends: back to Anna's preset, and her turn passes to Ben, who waits
        main.send(type="player", song=SONG, position=20.0, ended=True)
        ben.next("you", lambda y: y["in_control"], limit=2000)
        assert state.mode == "manual" and state.preset == "solid" and state.queue.controller is not None
        anna_you = anna.next("you", lambda y: not y["in_control"], limit=2000)
        assert anna_you["position"] is None  # out of the queue; joining again means the back of the line
        ben.send(type="set_preset", preset="rainbow")
        ben.next("state", lambda s: s["manual"]["preset"] == "rainbow")

        # the fake logs told the story, to the logging page only
        lines = []
        wait_until = time.monotonic() + 3
        while time.monotonic() < wait_until and not any("stream open: Never Gonna" in line["text"] for line in lines):
            lines += logging_page.next("log")["lines"]
        texts = " | ".join(line["text"] for line in lines)
        for event in ("acquired control", "stream open: Never Gonna", "=== rebuilding"):
            assert event in texts, event
        for phone in (anna, ben):
            assert all(msg["type"] != "log" for msg in phone.seen)

        for browser in (main, logging_page, anna, ben):
            browser.close()

    assert client.app.state.tasks.running == []  # everything stopped cleanly
