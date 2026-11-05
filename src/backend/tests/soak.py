"""The soak test (plan step 10): the whole backend for a long while, the way
an open day treats it.

    ./dod backend-soak --minutes 30

The stand: the real app on a real uvicorn server (inside this container,
nothing published), with the simulated board – unplugged now and then.
The visitors, in a separate process so their work doesn't slow the server
down and spoil the numbers:

- 8 phones: they queue, drag sliders, draw, pick songs, reload, go quiet
  until they lose their turn, flood the server now and then, and sometimes
  come back as a new visitor
- a main screen: it plays the songs like the real one (position once a
  second, the spectrum 30 times a second, the end), closes and reopens, and
  now and then a second one replaces it
- a logging page

Passes when, after a minute's warm-up: no errors in the log and no task
restarted, memory within ±10 MB of where it settled, and the render loop at
30 fps (±1) every second.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import multiprocessing
import os
import random
import secrets
import sys
import tempfile
import time
from pathlib import Path

PORT = 8765
KEY = "soak"
PHONES = 8
SONGS = [("dQw4w9WgXcQ", "Never Gonna", 25.0), ("y6120QOlsfU", "Sandstorm", 18.0)]
WARMUP = 60.0  # seconds before memory and fps count
FPS_TOLERANCE = 1.0
MEMORY_TOLERANCE_MB = 10.0
UNPLUG_EVERY = (60.0, 120.0)  # seconds between unplugging the board
UNPLUG_FOR = (3.0, 10.0)


# --- the visitors (in their own process) --------------------------------------


def random_value(param, rng):
    kind = param["kind"]
    if kind == "slider":
        step = param["step"] or 0.01
        steps = round((param["max"] - param["min"]) / step)
        return round(param["min"] + rng.randint(0, steps) * step, 6)
    if kind == "color":
        return f"#{rng.randrange(1 << 24):06x}"
    if kind == "choice":
        return rng.choice(param["options"])["value"]
    return rng.random() < 0.5


async def nap(seconds, stop_at):
    """asyncio.sleep, cut short at the end of the run."""
    await asyncio.sleep(max(0.0, min(seconds, stop_at - time.monotonic())))


class Stats:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.problems: list[str] = []

    def add(self, name, n=1):
        self.counts[name] = self.counts.get(name, 0) + n


async def phone(n, url, stop_at, stats):
    import websockets

    rng = random.Random(n)
    token = secrets.token_hex(16)
    while time.monotonic() < stop_at:
        if rng.random() < 0.1:
            token = secrets.token_hex(16)  # a new visitor (another phone, an incognito window)
        me = {"you": None, "preset": None}
        try:
            async with websockets.connect(f"{url}/ws?role=phone", additional_headers={"cookie": f"dod_session={token}"},
                                          max_size=2**20) as ws:
                welcome = json.loads(await ws.recv())
                presets = welcome["presets"]

                async def read():
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg["type"] == "you":
                            me["you"] = msg
                        elif msg["type"] == "state":
                            me["preset"] = msg["manual"]["preset"]  # a real phone shows only its controls
                        elif msg["type"] == "error":
                            stats.add(f"error {msg['code']}")
                        elif msg["type"] == "log":
                            stats.problems.append(f"phone {n} got a log message")

                reader = asyncio.create_task(read())
                stats.add("phone sessions")
                session_end = time.monotonic() + rng.uniform(30, 180)  # then a reload
                while time.monotonic() < min(session_end, stop_at):
                    you = me["you"]
                    r = rng.random()
                    if you is None or you["position"] is None:
                        if r < 0.3:
                            await ws.send(json.dumps({"type": "join_queue"}))
                            stats.add("joins")
                    elif you["in_control"]:
                        if r < 0.15:
                            await ws.send(json.dumps({"type": "set_preset", "preset": rng.choice(presets)["id"]}))
                        elif r < 0.55:  # a slider dragged: ~10 values a second for a second or two
                            preset = next((p for p in presets if p["id"] == me["preset"]), None)
                            if preset is not None and preset["params"]:
                                param = rng.choice(preset["params"])
                                for _ in range(rng.randint(5, 20)):
                                    await ws.send(json.dumps({"type": "set_param", "name": param["name"],
                                                              "value": random_value(param, rng)}))
                                    await asyncio.sleep(0.1)
                        elif r < 0.7:
                            drawing = "".join(f"{rng.randrange(256):02x}" for _ in range(8))
                            await ws.send(json.dumps({"type": "set_matrix", "mode": rng.choice(["drawing", "icon"]),
                                                      "drawing": drawing}))
                        elif r < 0.75:
                            await ws.send(json.dumps({"type": "loading_started"}))
                            await ws.send(json.dumps({"type": "play_song", "song": rng.choice(SONGS)[0]}))
                            stats.add("songs picked")
                        elif r < 0.78:
                            await nap(rng.uniform(5, 40), stop_at)  # looks away; maybe long enough to lose the turn
                        elif r < 0.8:
                            await ws.send(json.dumps({"type": "leave_queue"}))
                    elif r < 0.02:
                        await ws.send(json.dumps({"type": "leave_queue"}))
                    if rng.random() < 0.005:  # a flood: the rate limit has to hold
                        for _ in range(100):
                            await ws.send(json.dumps({"type": "set_preset", "preset": "rainbow"}))
                        stats.add("floods")
                    await nap(rng.uniform(0.2, 1.5), stop_at)
                reader.cancel()
        except Exception as e:  # the server closed us (shutdown), or a bug
            if time.monotonic() < stop_at - 2:
                stats.problems.append(f"phone {n}: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


async def main_screen(url, stop_at, stats):
    import websockets

    rng = random.Random(99)
    token = secrets.token_hex(16)
    cookie = f"dod_session={token}; dod_internal={KEY}"
    while time.monotonic() < stop_at:
        try:
            async with websockets.connect(f"{url}/ws?role=main", additional_headers={"cookie": cookie}) as ws:
                stats.add("main sessions")
                music = {"song": None, "length": 0.0, "since": 0.0, "ended": False}

                async def read():
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg["type"] == "state":
                            song = msg["music"]["song"]
                            if song != music["song"]:
                                music.update(song=song, length=msg["music"]["length"] or 0.0,
                                             since=time.monotonic(), ended=False)
                                if song is not None:
                                    stats.add("songs played")

                async def play():
                    last_position = 0.0
                    while True:
                        await asyncio.sleep(1 / 30)
                        song = music["song"]
                        if song is None or music["ended"]:
                            continue
                        position = time.monotonic() - music["since"]
                        beat = position % 0.5 < 0.07
                        bands = [min(1.0, rng.random() * (1.0 if i < 8 else 0.5) + (0.4 if beat and i < 4 else 0)) for i in range(32)]
                        await ws.send(json.dumps({"type": "spectrum", "bands": bands, "beat": beat}))
                        if position >= music["length"]:
                            music["ended"] = True
                            await ws.send(json.dumps({"type": "player", "song": song, "position": music["length"], "ended": True}))
                        elif position - last_position >= 1:
                            last_position = position
                            await ws.send(json.dumps({"type": "player", "song": song, "position": position, "ended": False}))

                tasks = [asyncio.create_task(read()), asyncio.create_task(play())]
                await nap(rng.uniform(60, 240), stop_at)
                if rng.random() < 0.2:  # a second window replaces this one (the server closes it with 4001)
                    async with websockets.connect(f"{url}/ws?role=main", additional_headers={"cookie": cookie}) as second:
                        await second.recv()
                        stats.add("main replaced")
                        await asyncio.sleep(2)
                for t in tasks:
                    t.cancel()
            stats.add("main closed")
            await nap(rng.uniform(2, 15), stop_at)  # closed; long enough and the song ends as player_gone
        except Exception as e:
            if time.monotonic() < stop_at - 2:
                stats.problems.append(f"main: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


async def logging_page(url, stop_at, stats):
    import websockets

    cookie = f"dod_session={secrets.token_hex(16)}; dod_internal={KEY}"
    while time.monotonic() < stop_at:
        try:
            async with websockets.connect(f"{url}/ws?role=logging", additional_headers={"cookie": cookie},
                                          max_size=2**22) as ws:
                end = time.monotonic() + random.uniform(120, 300)  # then a reload
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg["type"] == "log":
                        stats.add("log lines", len(msg["lines"]))
                    if time.monotonic() > min(end, stop_at):
                        break
        except Exception as e:
            if time.monotonic() < stop_at - 2:
                stats.problems.append(f"logging: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


def visitors(url, seconds, results):
    """The other process: every visitor at once, then the counts back to the server's side."""
    stats = Stats()

    async def all_of_them():
        stop_at = time.monotonic() + seconds
        crowd = asyncio.gather(main_screen(url, stop_at, stats), logging_page(url, stop_at, stats),
                               *(phone(n, url, stop_at, stats) for n in range(PHONES)))
        try:
            await asyncio.wait_for(crowd, timeout=seconds + 5)  # whoever is still busy is cut off
        except TimeoutError:
            pass

    asyncio.run(all_of_them())
    results.put((stats.counts, stats.problems[:50]))


# --- the stand (this process) -------------------------------------------------


class Errors(logging.Handler):
    """Every ERROR or worse from the backend, the HCL and uvicorn."""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(f"{record.name}: {record.getMessage()}")


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def cache_with_songs(folder: Path) -> Path:
    """Fake downloads: the soak tests the backend, not YouTube."""
    for song_id, title, length in SONGS:
        (folder / f"{song_id}.mp4").write_bytes(b"\x00" * 1024)
        (folder / f"{song_id}.json").write_text(json.dumps({"id": song_id, "title": title, "length": length}))
    songs = folder / "songs.txt"
    songs.write_text("".join(f"https://youtu.be/{i}  {t}\n" for i, t, _ in SONGS))
    return songs


async def stand(seconds: float) -> int:
    import uvicorn
    from hcl.testing import sim_link

    from dod.main import create_app
    from dod.settings import Settings

    folder = Path(tempfile.mkdtemp(prefix="soak-"))
    songs = cache_with_songs(folder)
    # short turns and limits, so the queue's rules all happen many times
    settings = Settings(internal_key=KEY, cache_dir=folder, turn_seconds=40, inactive_seconds=12, idle_seconds=20)
    link, board = sim_link()
    app = create_app(settings, link=link, songs_file=songs)
    errors = Errors()
    for name in ("dod", "hcl", "uvicorn.error", "uvicorn"):
        logging.getLogger(name).addHandler(errors)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, ws_max_size=65536, log_level="warning",
                                           timeout_graceful_shutdown=5))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    results: multiprocessing.Queue = multiprocessing.get_context("spawn").Queue()
    crowd = multiprocessing.get_context("spawn").Process(target=visitors, args=(f"ws://127.0.0.1:{PORT}", seconds, results))
    crowd.start()

    start = time.monotonic()
    next_unplug = start + random.uniform(*UNPLUG_EVERY)
    unplugged_until = None
    baseline = None
    rss_seen: list[float] = []
    fps_bad: list[str] = []
    unplugs = 0
    minute_fps: list[float] = []
    loop = app.state.loop
    while crowd.is_alive() or time.monotonic() - start < seconds:
        await asyncio.sleep(1)
        now = time.monotonic()
        elapsed = now - start
        if unplugged_until is None and now >= next_unplug:
            board.unplug()
            unplugs += 1
            unplugged_until = now + random.uniform(*UNPLUG_FOR)
        elif unplugged_until is not None and now >= unplugged_until:
            board.replug()
            unplugged_until = None
            next_unplug = now + random.uniform(*UNPLUG_EVERY)
        fps = loop.fps
        rss = rss_mb()
        if elapsed >= WARMUP:
            baseline = baseline if baseline is not None else rss
            rss_seen.append(rss)
            minute_fps.append(fps)
            if abs(fps - 30) > FPS_TOLERANCE:
                fps_bad.append(f"{elapsed:.0f} s: {fps} fps")
        if int(elapsed) % 60 == 0 and elapsed >= 1:
            low, high = (min(minute_fps), max(minute_fps)) if minute_fps else (fps, fps)
            print(f"[{elapsed / 60:4.1f} min] fps {low}-{high}  memory {rss:.1f} MB  mode {app.state.state.mode:6}  "
                  f"waiting {len(app.state.state.queue.waiting)}  unplugs {unplugs}  errors {len(errors.records)}  "
                  f"connections {len(app.state.hub.connections)}", flush=True)
            minute_fps.clear()
        if elapsed > seconds + 30:
            break

    try:
        counts, problems = results.get(timeout=20)  # before join(): a full queue would keep the process alive
    except Exception:
        counts, problems = {}, ["the visitors sent no results"]
    crowd.join(timeout=10)
    restarts = {name: n for name, n in app.state.tasks.restarts.items() if n}
    server.should_exit = True
    await serving

    drift = (max(abs(r - baseline) for r in rss_seen) if rss_seen and baseline is not None else 0.0)
    print("\n--- soak", f"{seconds / 60:.1f} min")
    print("visitors:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"board unplugged {unplugs} times; memory {baseline or 0:.1f} MB after warm-up, "
          f"max drift {drift:.1f} MB (≤ {MEMORY_TOLERANCE_MB}); fps off {len(fps_bad)} times")
    failures = []
    if errors.records:
        failures.append(f"{len(errors.records)} errors in the log: " + "; ".join(errors.records[:5]))
    if restarts:
        failures.append(f"tasks restarted: {restarts}")
    if drift > MEMORY_TOLERANCE_MB:
        failures.append(f"memory drifted {drift:.1f} MB")
    if fps_bad:
        failures.append(f"render loop off 30 fps: {', '.join(fps_bad[:5])}")
    if problems:
        failures.append("visitors: " + "; ".join(problems[:5]))
    for f in failures:
        print("FAIL:", f)
    print("PASS" if not failures else "FAILED")
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="./dod backend-soak", description=__doc__.split("\n\n")[0])
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--seconds", type=float, default=None, help="instead of minutes, for a quick try")
    args = parser.parse_args()
    seconds = args.seconds if args.seconds is not None else args.minutes * 60
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    return asyncio.run(stand(seconds))


if __name__ == "__main__":
    sys.exit(main())
