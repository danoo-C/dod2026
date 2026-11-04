# Handoff – 2026-11-04

Where the build stands at the end of the day, and what to do next.
Details are in [plans/backend.md](plans/backend.md) and
[plans/frontend.md](plans/frontend.md) (each finished step has a "Built"
note) and the design in [backend.md](backend.md).

## Where things stand

- **HCL stage 1:** done earlier (the board's code and the Windows bridge,
  stages 2 and 3, are not started).
- **Backend: steps 0–9 of 10 done.** The backend runs against the
  simulated board: phones can get a session, join the queue, take control,
  pick presets, change parameters and draw on the 8x8; the main screen can
  control and use the admin commands; every browser gets state, its own queue
  position and live previews over the WebSocket; `main` and `logging` get the
  fake logs, starting with the last 300 lines.
- **Frontend: steps 1–6 of 8 done** (tooling, the connection, the shared
  components, the logging page, the phone, the main screen). React + Vite in `src/frontend/`, `./dod sim` runs the backend
  and Vite together on http://localhost:5173. Every screen connects with its
  role and reconnects by itself; the components (preview, terminal, loading
  screen, QR, countdown, badge, toast) have the mockup's look, and
  http://localhost:5173/components.html shows them all with fake data.
  All three screens are real: `/` the phone (queue, loading, presets and
  their parameters, drawing, songs, time's up), `/internal/main` the
  notebook's screen ("Spustiť", the terminal, QR codes, queue, preview,
  the admin panel on Ctrl+Alt+D; the video comes with step 7),
  `/internal/logging` the terminal alone.
- **Tests:** `./dod test` is green – HCL 165 tests (~23 s), backend 793
  (~22 s, most of them the presets at every parameter extreme), frontend 166
  (~4 s, plus the type checks).
- **Git:** `dod2026/` is its own repo (branch `main`, no remote yet).

| Step | What | State |
|---|---|---|
| 0 | `hcl.testing` (simulated board for tests) | done |
| 1 | tooling: package, Dockerfile, `./dod` commands | done |
| 2 | settings, event bus | done |
| 3 | engine core: picture, output pipeline (flash + power limit), first effects | done |
| 4 | `hardware.py`, 30 fps render loop, `/api/status` | done |
| 5 | state, sessions, queue | done |
| 6 | API: messages, WebSocket hub, HTTP, JSON Schema | done |
| 7 | the remaining presets, the 8x8 per preset | done |
| 8 | music: downloads, player, spectrum → light | done (`./dod songs` for the rest of the list) |
| 9 | the fake logs | done |
| 10 | end to end + 30 min soak | after 7–9 |

## What to do next

1. **`./dod songs`** – download the rest of the list (one song,
   `dQw4w9WgXcQ`, is in `cache/` already; ~30 MB and ~15 s each). The list is
   `src/backend/dod/music/songs.txt`; change it freely. Then **frontend step
   7** (the player and the spectrum on the main screen) – recommended next,
   nothing blocks it.
2. **Look at `./dod sim` in a Windows browser** (http://localhost:5173) –
   the hand checks of frontend steps 1 and 2, not done yet:
   - an edit to `src/frontend/src/screens/Phone.tsx` shows up without a reload
   - `docker restart dod2026-backend` in another terminal (Vite keeps
     running): the page says "Odpojené, pripájam znova…" for a moment and
     comes back by itself
   - open `/internal/main?key=dev` in two windows: the first one says
     "Otvorené v inom okne", "Prevziať" takes it back
   - "Postaviť sa do radu" on `/`: the countdown runs
   - http://localhost:5173/components.html: every component looks like the
     mockup (`docs/preview.html`), the terminal scrolls, the loading screen
     runs 2–4 s
   - the phone in two windows, a normal and a private one (two visitors;
     the browser's phone view, F12 → device toolbar, makes them phone-sized):
     join in both → the first gets the loading screen, then the controls;
     presets, every parameter, a drawing show up in the other's preview; after
     3 min "Tvoj čas skončil" and the second one's turn. On real phones once
     WSL's networking is changed.
   - http://localhost:5173/internal/main?key=dev, full screen (F11), at
     1920×1080 and 1366×768: "Spustiť", then nothing overflows, the terminal
     is readable from 2 m; Ctrl+Alt+D opens the admin panel, and skip /
     pause / stop act on the phone windows. With
     `DOD_WIFI_SSID=… DOD_WIFI_PASSWORD=… ./dod sim` the Wi-Fi QR code shows
     too; scan both from 1.5 m.
   - http://localhost:5173/internal/logging?key=dev: opens full of lines,
     keeps scrolling, a reload is full again at once; left open for an hour
     in Edge, the tab's memory stays flat (Task Manager)
   For a phone, WSL's NAT mode needs a change on Windows first (frontend
   plan, step 1, "Built").
3. **After frontend step 7:** backend step 10 and frontend step 8 (end to
   end). Backend
   step 10 and frontend step 8 (end to end) come after those. Until the
   answers come, the hand checks above are what's left. The hotspot's name
   and password are open too (for the Wi-Fi QR code; until then only the
   page's QR code shows). `docs/preview.html` is the clickable mockup the
   screens follow.

## How to pick up

```sh
cd ~/spseke/dod2026
./dod test                 # all three suites; ./dod test backend -x for one
./dod sim                  # backend + Vite: http://localhost:5173, simulated board, both reload on save
                           # internal pages: /internal/main?key=dev
./dod backend              # the backend alone on http://localhost:8000 (serves the last frontend build)
./dod frontend-build       # build the frontend for the backend to serve
./dod schema               # after changing a message in dod/api/messages.py (also writes the TS types)
./dod npm <args>           # e.g. ./dod npm install --save-exact <package>
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
