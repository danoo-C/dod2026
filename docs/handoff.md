# Handoff – 2026-11-04

Where the build stands at the end of the day, and what to do next.
Details are in [plans/backend.md](plans/backend.md) (each finished step has a
"Built" note) and the design in [backend.md](backend.md).

## Where things stand

- **HCL stage 1:** done earlier (the board's code and the Windows bridge,
  stages 2 and 3, are not started).
- **Backend: steps 0–6 and 9 of 10 done.** The backend runs against the
  simulated board: phones can get a session, join the queue, take control,
  pick presets, change parameters and draw on the 8x8; the main screen can
  control and use the admin commands; every browser gets state, its own queue
  position and live previews over the WebSocket; `main` and `logging` get the
  fake logs, starting with the last 300 lines.
- **Tests:** `./dod test` is green – HCL 165 tests (~23 s), backend 414
  (~19 s). The last three full runs were all green.
- **Git:** `dod2026/` is its own repo now (branch `main`, one initial
  commit plus step 9, no remote yet).

| Step | What | State |
|---|---|---|
| 0 | `hcl.testing` (simulated board for tests) | done |
| 1 | tooling: package, Dockerfile, `./dod` commands | done |
| 2 | settings, event bus | done |
| 3 | engine core: picture, output pipeline (flash + power limit), first effects | done |
| 4 | `hardware.py`, 30 fps render loop, `/api/status` | done |
| 5 | state, sessions, queue | done |
| 6 | API: messages, WebSocket hub, HTTP, JSON Schema | done |
| 7 | the remaining presets | **waiting for you:** what the 8x8 shows in manual mode |
| 8 | music: downloads, player, spectrum → light | **waiting for you:** the song list |
| 9 | the fake logs | done |
| 10 | end to end + 30 min soak | after 7–9 |

## What to do next

1. **Answer the two open questions**, so steps 7 and 8 aren't blocked:
   - **the 8x8 in manual mode** (tech-spec 5.3): an icon per preset,
     the strip as bars, a face, the drawing only, or a mix. Drawing already
     works; solid and rainbow show placeholders (a frame, moving stripes).
   - **the song list:** YouTube links, each with a short title for the phone
     (YouTube's own titles are too long). Max ~7 min per song.
2. **Confirm the frontend plan's decisions** ([plans/frontend.md](plans/frontend.md),
   the numbered list under "Starting point"), then start its step 1
   (tooling). Steps 1–6 need nothing from the backend's open steps; step 7
   (music) waits for backend step 8. `docs/preview.html` is the clickable
   mockup the screens follow.

## How to pick up

```sh
cd ~/spseke/dod2026
./dod test                 # both suites; ./dod test backend -x for one
./dod backend              # http://localhost:8000, simulated board, reloads on save
                           # internal pages: /internal/main?key=dev
./dod schema               # after changing a message in dod/api/messages.py
```

- **In Claude Code, `./dod` must run outside the sandbox** (Docker's socket
  is blocked inside it: "permission denied … docker.sock"). tech-spec 7.1 says
  so too.
- Any `DOD_*` variable in your shell reaches the container, e.g.
  `DOD_BRIGHTNESS=0.3 ./dod backend`. A wrong one stops the backend with a
  message naming it.
- Quick look at a running backend: `curl localhost:8000/api/status` (board
  link, render fps, mode, tasks, connections).

## Things built today that the next steps plug into

**Step 8 (music)**

- `Hub(..., songs=, play_song=, on_spectrum=, on_player=)` in
  `dod/api/ws.py`: the player plugs in here. Until then `play_song` answers
  `no_player` (no main screen) or `unknown_song`.
- `app.state.songs` in `dod/main.py` returns `[]`; `/api/songs` and
  `welcome` read it.
- `State.song_started(song, title, length, by)` and
  `State.song_ended(reason)` keep the mode and the queue right; the player
  only decides *when* (the three endings in backend.md 6).
- `SceneSync.MUSIC_EFFECT` in `dod/main.py` is the rainbow as a placeholder
  until the music effect exists.
- `/media/<id>.mp4` doesn't exist yet; its rules are in backend.md 9 (id
  check against the list before touching the file system, range requests).

**Step 8 and the logs** (step 9 is built)

- `SongStarted` already starts a burst and writes `stream open: …`.
- `Facts.beat` in `dod/logs/templates.py` is `None`, so the `fft` line
  (`32 bins ok, peak 112 Hz, beat=1`) never shows; the music effect should
  hand its beat to `log_facts()` in `dod/main.py`.

**Step 7 (presets)**

- Every effect is checked automatically: right shape for 1/10/60 LEDs at every
  parameter extreme, deterministic, and never triggers the flash limit
  (`tests/test_engine_effects.py`). New presets go into
  `dod/engine/effects/__init__.py`.

## Decided while building (all written into backend.md)

- The queue and every screen use a **public id** (hash of the session
  cookie); the cookie itself never leaves `control/sessions.py` (9).
- A song ending with nobody waiting makes the turn "over"; it ends when
  someone joins. Your own song keeps you in control even with the phone
  locked. A waiting visitor offline for 30 s leaves the line (8).
- The stand starts in **idle**, not the rainbow (6).
- The internal cookie is set by `/api/session?key=…` (HttpOnly). Error code
  `forbidden`; close codes 4400 / 1009 / 1001 (9).
- A 20 Hz strobe through the flash limit comes out as 3 quick flashes, then a
  pause; the strobe preset itself must stay under the limit (7.3).
- `/api/status` returns `link`, `render`, `tasks`, `connections` (5.6).
- tech-spec 6.3 mounted the songs at `/app/cache`; fixed to `/work/cache`.

## Loose ends worth knowing

- **HCL suite takes ~23 s** – close to the 30 s budget in its plan. The
  backend suite is separate (~19 s, ~3.5 s of it the log tests); step 10
  wants it under 30 s too.
- When the board's LED count changes, the flash limiter starts its count over,
  so across that one moment up to 12 transitions could fall into one second.
  Rare (a different board plugged in); not documented in backend.md yet.
- `SceneSync` (state → render loop) lives in `dod/main.py`; it may want its
  own module once music and drawing logic grow.
- Still marked **(verify)** in tech-spec, for phases 3–4: the serial bridge's
  speed through Docker Desktop, the hotspot's 8-device limit, phones on a
  Wi-Fi without internet.
