"""The fake logs (docs/backend.md 10, plan step 9): with a fixed seed and a
fake clock, then through the app with TestClient."""

import math
import random
import re
import time

import pytest
from fastapi.testclient import TestClient
from hcl.testing import sim_link

from dod.bus import (
    BoardConnected,
    BoardIncompatible,
    BoardLog,
    BoardLost,
    BoardText,
    Bus,
    DrawingChanged,
    LoadingStarted,
    ParamChanged,
    PresetChanged,
    QueueJoined,
    QueueLeft,
    SongEnded,
    SongStarted,
    TurnEnded,
    TurnStarted,
)
from dod.control.sessions import SESSION_COOKIE, INTERNAL_COOKIE, new_token, public_id
from dod.logs import templates
from dod.logs.generator import BURST_GAP, HISTORY, STEP_SECONDS, LogGenerator
from dod.logs.templates import FILLER, LEVELS, Facts
from dod.main import create_app
from dod.settings import Settings

STEP = STEP_SECONDS
WALL0 = 1_793_710_000.0
PUBLIC = public_id(new_token())

FULL = Facts(frame_no=8412, bytes_tx=302_211, link_fps=29.9, render_fps=30.0, rtt_ms=4.2, led_count=10,
             mode="manual", preset="rainbow", connections=5, waiting=2, frame=bytes(range(38)), beat=True)

EVERY_EVENT = [
    PresetChanged(preset="rainbow", by="7f3a"),
    ParamChanged(preset="rainbow", name="speed", value=0.7, by="7f3a"),
    ParamChanged(preset="solid", name="color", value="#FF8000", by="main"),
    ParamChanged(preset="solid", name="fade", value=True, by=None),
    DrawingChanged(by="7f3a"),
    SongStarted(song="dQw4w9WgXcQ", title="Never Gonna", by="7f3a"),
    SongEnded(song="dQw4w9WgXcQ", reason="ended"),
    TurnStarted(session=PUBLIC, waiting=2),
    TurnEnded(session=PUBLIC, reason="time"),
    QueueJoined(session=PUBLIC, position=3),
    QueueLeft(session=PUBLIC),
    QueueLeft(session=PUBLIC, reason="gone"),
    BoardConnected(led_count=10, firmware="0.1.0", simulated=True, rebooted=True),
    BoardLost(reason="read timeout"),
    BoardLog(level="INFO", text="frames ok"),
    BoardLog(level="ERROR", text="brownout\ndetected"),
]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Run:
    """A generator with a fixed seed and a fake clock; every batch it sends is kept."""

    def __init__(self, seed=1, facts=FULL):
        self.bus = Bus()
        self.clock = Clock()
        self.batches = []
        self.gen = LogGenerator(self.bus, send=self.batches.append, facts=lambda: facts,
                                rng=random.Random(seed), clock=self.clock, wall=lambda: WALL0)
        self.gen.step(self.clock.t)  # the first step at a whole second, so filler seconds line up

    def advance(self, seconds, every=None):
        """Step through `seconds` like the task does; `every(t)` runs before each step."""
        for _ in range(round(seconds / STEP)):
            self.clock.t = round(self.clock.t + STEP, 6)
            if every is not None:
                every(self.clock.t)
            self.gen.step(self.clock.t)

    @property
    def lines(self):
        return [line for batch in self.batches for line in batch]

    def since(self, t):
        return [line for line in self.lines if line.t >= WALL0 + (t - 100.0) - 1e-6]


# --- calm, bursts -------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_calm_rate_is_3_to_8_lines_a_second(seed):
    run = Run(seed)
    run.advance(60)
    per_second = [0] * 60
    for line in run.lines:
        # a line due in second k is written at the first step at or after it: (k, k + 1]
        per_second[math.ceil(round(line.t - WALL0, 2)) - 1] += 1
    assert all(3 <= n <= 8 for n in per_second), per_second
    assert len(set(per_second)) > 2  # it varies


def test_a_burst_is_30_to_50_lines_within_2_seconds():
    for seed in range(10):
        run = Run(seed)
        run.advance(5)
        run.bus.publish(LoadingStarted(by="7f3a"))
        run.advance(4)
        texts = [line.text for line in run.lines]
        first = next(i for i, text in enumerate(texts) if text.startswith("=== rebuilding"))
        last = next(i for i, text in enumerate(texts) if "ready in" in text)
        burst = run.lines[first:last + 1]  # no filler in between: it pauses
        assert 30 <= len(burst) <= 50, len(burst)
        assert burst[-1].t - burst[0].t <= 2.0
        assert run.gen.bursts == 1


def test_filler_pauses_during_a_burst_and_comes_back():
    run = Run()
    run.advance(2)
    start = run.clock.t
    run.bus.publish(LoadingStarted(by=None))
    run.advance(8)
    after = [line for line in run.since(start + 2.5)]
    assert 3 * 5 <= len(after) <= 8 * 6  # 5.5 s of calm again


def test_loading_started_ten_times_a_second_still_bursts_once_per_3_seconds():
    run = Run()
    run.advance(1)
    run.advance(12, every=lambda t: round(t * 100) % 10 == 0 and run.bus.publish(LoadingStarted(by="7f3a")))
    assert run.gen.bursts == 4  # at 0, 3, 6 and 9 s of the 12
    starts = [line.t for line in run.lines if line.text.startswith("=== rebuilding")]
    assert len(starts) == 4
    assert all(b - a >= BURST_GAP - 1e-6 for a, b in zip(starts, starts[1:]))


def test_a_song_bursts_and_shares_the_limit_with_loading():
    run = Run()
    run.bus.publish(LoadingStarted(by="7f3a"))
    run.advance(1)
    run.bus.publish(SongStarted(song="dQw4w9WgXcQ", title="Never Gonna", by="7f3a"))
    run.advance(1)
    assert run.gen.bursts == 1  # within 3 s of the loading burst
    assert any("stream open: Never Gonna" in line.text for line in run.lines)  # the event itself still shows
    run.advance(2)
    run.bus.publish(SongStarted(song="dQw4w9WgXcQ", title="Never Gonna", by="7f3a"))
    run.advance(1)
    assert run.gen.bursts == 2


def test_at_most_one_batch_per_step():
    run = Run()
    run.bus.publish(LoadingStarted(by=None))
    run.advance(10)
    assert len(run.batches) <= 10 / STEP
    assert all(batch for batch in run.batches)  # nothing empty is sent


def test_a_stalled_clock_does_not_catch_up():
    run = Run()
    run.advance(1)
    before = len(run.lines)
    run.clock.t += 30  # the process was paused for 30 s
    run.gen.step(run.clock.t)
    assert len(run.lines) - before <= 8


def test_same_seed_same_lines():
    a, b = Run(seed=7), Run(seed=7)
    a.advance(5)
    b.advance(5)
    assert [(x.tag, x.text) for x in a.lines] == [(y.tag, y.text) for y in b.lines]


def test_times_never_go_backwards():
    run = Run()
    run.bus.publish(LoadingStarted(by=None))
    run.advance(10)
    times = [line.t for line in run.lines]
    assert times == sorted(times)
    assert WALL0 < times[0] < WALL0 + 1


# --- templates ----------------------------------------------------------------


@pytest.mark.parametrize("facts", [Facts(), FULL, Facts(mode="music", beat=False, frame=b"\x00")],
                         ids=["nothing yet", "everything", "music"])
def test_every_template_fills_in(facts):
    for seed in range(50):
        r = random.Random(seed)
        for template in FILLER:
            text = template.fill(r, facts)
            assert text is None or (isinstance(text, str) and text and "\n" not in text), template
            assert template.level in LEVELS
        tag, level, text = templates.filler(r, facts)
        assert level in LEVELS and text
        for kind in ("loading", "song"):
            lines = templates.burst(kind, r, facts)
            assert 30 <= len(lines) <= 50
            assert all(level in LEVELS and text and "\n" not in text for _, level, text in lines)


def test_progress_bars():
    assert templates.bar(0) == "[--------------------]   0%"
    assert templates.bar(0.52) == "[##########----------]  52%"
    assert templates.bar(1) == "[####################] 100%"


def test_every_event_gives_a_line_or_stays_out_on_purpose():
    for event in EVERY_EVENT:
        lines = templates.event_lines(event)
        assert lines, event
        assert all(level in LEVELS and "\n" not in text for _, level, text in lines)
    # real problems go to docker logs and the badge, never the fake terminal
    assert templates.event_lines(BoardText(line="Traceback (most recent call last):")) == []
    assert templates.event_lines(BoardIncompatible(reason="protocol 2", protocol=2)) == []
    assert templates.event_lines(LoadingStarted(by=None)) == []  # only a burst


def test_lines_show_the_short_id_only():
    lines = templates.event_lines(TurnStarted(session=PUBLIC, waiting=2))
    assert lines == [("queue", "INFO", f"session {PUBLIC[:4]}… acquired control (2 waiting)")]
    assert PUBLIC not in str(lines)


def test_board_text_is_one_short_line():
    [(tag, level, text)] = templates.event_lines(BoardLog(level="ERROR", text="x" * 500 + "\nmore"))
    assert tag == "esp32" and level == "WARN" and "\n" not in text and len(text) <= templates.MAX_TEXT


def test_real_numbers_show_up():
    texts = [templates.filler(random.Random(seed), FULL)[2] for seed in range(300)]
    assert "frame 008412 committed (38 B, sum 0xbf)" in texts
    assert "tx 00 01 02 03 04 05 06 07 08 09 …" in texts
    assert any(text.startswith("render 30.0 fps, link 29.9 fps, 10 leds") for text in texts)


# --- real events in the stream ------------------------------------------------


def test_real_events_show_up_within_a_second():
    run = Run()
    run.advance(1)
    for event in EVERY_EVENT:
        start = run.clock.t
        run.bus.publish(event)
        run.advance(1)
        texts = [line.text for line in run.since(start)]
        for _, _, text in templates.event_lines(event):
            assert text in texts, event


def test_a_dragged_slider_is_one_line_per_half_second_with_the_latest_value():
    run = Run()
    values = iter(range(1000))

    def drag(t):
        run.bus.publish(ParamChanged(preset="rainbow", name="speed", value=next(values) / 100, by="7f3a"))

    run.advance(2, every=drag)  # 20 changes a second
    run.advance(1)
    speed = [line.text for line in run.lines if "rainbow.speed" in line.text]
    assert 4 <= len(speed) <= 5
    assert speed[-1] == "rainbow.speed = 0.39 (session 7f3a…)"  # the last value made it


def test_a_broken_facts_reader_does_not_stop_the_logs():
    run = Run(facts=None)
    run.gen._facts = lambda: 1 / 0
    run.advance(3)
    assert len(run.lines) >= 9


def test_history_keeps_the_last_300():
    run = Run()
    run.advance(120)
    history = run.gen.history()
    assert len(history) == HISTORY
    assert history == run.lines[-HISTORY:]


# --- through the app ----------------------------------------------------------

KEY = "test-key"


@pytest.fixture
def client():
    link, _ = sim_link()
    with TestClient(create_app(Settings(internal_key=KEY), link=link)) as c:
        yield c


def connect(client, role, key=None):
    cookie = f"{SESSION_COOKIE}={new_token()}" + (f"; {INTERNAL_COOKIE}={key}" if key else "")
    return client.websocket_connect(f"/ws?role={role}", headers={"cookie": cookie})


def test_a_logging_page_gets_the_last_lines_first(client):
    logs = client.app.state.logs
    deadline = time.monotonic() + 5
    while len(client.portal.call(logs.history)) < 5:  # the running generator writes 3-8 a second
        assert time.monotonic() < deadline, "no log lines"
        time.sleep(0.05)
    want = client.portal.call(logs.history)
    with connect(client, "logging", KEY) as ws:
        kinds = [ws.receive_json() for _ in range(4)]
        assert [k["type"] for k in kinds] == ["welcome", "state", "you", "log"]
        first = kinds[3]["lines"]
        assert len(first) >= len(want) and first[:len(want)] == [line.model_dump() for line in want]


def test_the_running_app_writes_logs_to_main_and_logging_only(client):
    with connect(client, "logging", KEY) as logging_page, connect(client, "phone") as phone:
        got = []
        for _ in range(400):
            msg = logging_page.receive_json()
            if msg["type"] == "log":
                got += msg["lines"]
            if len(got) >= 3:
                break
        assert len(got) >= 3
        assert all(re.fullmatch(r"[a-z0-9-]+", line["tag"]) and line["level"] in LEVELS for line in got)
        for _ in range(30):
            assert phone.receive_json()["type"] != "log"


def test_a_phone_loading_screen_starts_a_burst(client):
    with connect(client, "logging", KEY) as logging_page, connect(client, "phone") as phone:
        phone.receive_json()
        phone.send_json({"type": "loading_started"})
        for _ in range(600):
            msg = logging_page.receive_json()
            if msg["type"] == "log" and any(line["text"].startswith("=== rebuilding") for line in msg["lines"]):
                break
        else:
            raise AssertionError("no burst")
        assert client.app.state.logs.bursts == 1
