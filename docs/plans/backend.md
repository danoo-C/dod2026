# Plan: backend

How the backend gets built. The design is in [../backend.md](../backend.md);
this plan only says in which order, what each step produces, and how we know
it is done. Section numbers like "backend.md 7.3" point into the design.

## Goal

The whole backend runs against the simulated board (`DOD_SERIAL=sim`): phones
can queue and control the stand, the main screen can play songs and drive the
music mode, the logging page gets its lines – all over the WebSocket
protocol from backend.md 9. The frontend's plan starts from there.

## Starting point

- The HCL's stage 1 is done ([../hcl.md](../hcl.md), [its plan](hcl.md)): `from hcl import open_link,
  Frame` gives a connected simulated board.
- The decisions at the end of backend.md are taken as confirmed: package
  `dod`, no numpy, only `hardware.py` imports `hcl`, the whole state is
  broadcast on change, TypeScript types are generated from the Pydantic
  models, power limit 1500 mA – and the ones from the review on 2026-11-03
  (listed at the end of backend.md).
- Same rules as for the HCL: everything runs in Docker, absolute imports
  only, the package installed in editable mode in the image.

## Needed from you along the way

| What | Needed by |
|---|---|
| ~~what the 8x8 shows in manual mode (tech-spec 5.3)~~ decided in step 7 | step 7 |
| the song list: YouTube links of the songs for the stand, with a short title each | step 8 |

## Scope

Not part of this plan: the frontend (its own plan), the Windows launcher, the
board's code (HCL stages 2 and 3). Until the frontend exists, the page routes
serve a placeholder page. Step 0 is a small addition to the HCL that the
backend's tests need.

---

### Step 0. `hcl.testing` (backend.md 5.1, 12)

The backend's tests need a link to the simulated board **and** a handle on
the board (what it shows, unplugging it). Today that is only reachable through
`hcl.transport.sim`, which is not part of the HCL's API.

Files: `src/hcl/hcl/testing.py`, `src/hcl/hcl/transport/sim.py`,
`src/hcl/tests/`, `docs/hcl.md`

- `hcl.testing.sim_link(url="sim", **timings) -> (Link, SimBoard)` – a link
  to the simulated board with the fast test timings by default (today's
  `FAST` in `src/hcl/tests/support.py`), and a handle on the board
- `SimBoard`: `strip_rgb()`, `picture`, `frames_received`, `idle`, and new
  `unplug()` / `replug()`, so a test unplugs exactly when it wants instead of
  on the `unplug_every` timer
- the HCL's own tests share `FAST` with it, and `test_tools.py` uses
  `sim_link()` instead of its own copy. `Rig` in `test_link.py` stays as it
  is: it tests the HCL's insides (custom transports, the board's LOG
  messages), which `hcl.testing` deliberately doesn't offer
- hcl.md: `hcl.testing` in the public API (section 3.6), the simulated board
  (section 6), the backend's use (section 10) and the tests (section 11)

Done when:

- [x] `from hcl.testing import sim_link` works; `hcl/__init__.py` still
  doesn't export the transports
- [x] `board.unplug()` gives `Disconnected` on the link, `board.replug()`
  `Connected` again, both within the fast timings
- [x] the HCL suite is still green and under 30 s (165 tests, ~23 s)

Built: `SimTransport.unplug()` / `replug()` / `plugged`; the "unknown option"
check moved out of `open_link()` into `make_link_options()` in
`hcl/connect.py`, so `sim_link()` refuses the same typos;
`tests/test_testing.py` (7 tests). A board unplugged before `start()` also
works: the link keeps failing to open the port until `replug()`.

### Step 1. Tooling

Files:

- `src/backend/pyproject.toml` – package `dod`, Python ≥ 3.13; depends on
  `hcl`, `fastapi`, `uvicorn[standard]`, `pydantic`; dev: `pytest`,
  `pytest-timeout`, `httpx2` (for FastAPI's `TestClient`; Starlette 1.x
  deprecated plain `httpx`). `yt-dlp` comes in step 8. Versions pinned, like
  `hcl`'s. pytest timeout 15 s per test.
- `src/backend/dod/__init__.py`, `src/backend/dod/main.py` – an app with only
  `GET /api/health`
- `Dockerfile` – also installs `src/backend` in editable mode; `.dockerignore`
  lets its `pyproject.toml` in
- `dod` wrapper:
  - `./dod test` runs both suites (`src/hcl` and `src/backend`)
  - `./dod backend` runs uvicorn with `--reload`, `--ws-max-size 65536` and
    `DOD_INTERNAL_KEY=dev` on port 8000, published to WSL (`-p 8000:8000`, and
    so to Windows at `http://localhost:8000`)
- `src/backend/tests/test_imports.py` – absolute imports only; inside `dod/`
  only `hardware.py` imports `hcl`; tests import only `hcl` and `hcl.testing`
  (backend.md 5.1)
- tech-spec 7.1: add `./dod backend` (and later `./dod songs`,
  `./dod backend-soak`); note that `./dod dev` and `./dod sim` come with the
  frontend's plan

Done when:

- [x] `./dod build` builds the image with both packages
- [x] `./dod test` runs the HCL tests and the backend tests
- [x] `./dod backend` serves `/api/health`, reachable from Windows; editing a
  file reloads it
- [x] the import tests pass (and fail when a relative import, a second
  `import hcl` in `dod/`, or `hcl.transport` in a test is added)

Built:

- pins: `fastapi==0.162.0`, `uvicorn[standard]==0.54.0`, `pydantic==2.14.2`,
  `httpx2==2.16.0`; `pytest` and `pytest-timeout` share `hcl`'s pins, since
  both suites run in one image. The Dockerfile installs both packages in one
  pip call, so the backend's `hcl` dependency is the local one.
- `dod.main.create_app()` is a factory (`uvicorn --factory`): nothing is
  created at import time, and every test builds its own app.
- `./dod test` runs one pytest per suite (one docker run each), because each
  suite has its own pytest settings and both have a `tests/test_imports.py`;
  in one run their names would clash. `./dod test hcl|backend [args]` picks a
  suite, and so does a path (`./dod test src/backend/tests/...`).
- `./dod backend` runs as the container `dod2026-backend`, so a second one
  can't start by accident and fight over the port; it reloads on changes in
  `src/backend` and `src/hcl`.
- the import test checks its own checkers on snippets as well, and also
  that `hardware.py` (step 4) uses only `hcl` itself.
- checked by hand: `./dod backend` answered from WSL and from Windows
  PowerShell (`Invoke-WebRequest http://localhost:8000/api/health`); an edit
  to `main.py` was live within ~1 s. Three throwaway bad files made exactly the
  three import tests fail.

### Step 2. Settings and the bus (backend.md 4.3, 11)

Files: `dod/settings.py`, `dod/bus.py`, tests for both

- settings from the environment variables in backend.md 11, validated at
  startup: a wrong value stops the backend with a message naming the variable
- the bus: `publish(event)`, `subscribe()` with its own queue per listener,
  oldest dropped when a listener falls behind; the event dataclasses from
  backend.md 4.3

Done when:

- [x] every setting has its default; each kind of wrong value gives a clear error
- [x] two listeners get every event in order; a slow one loses its oldest and
  counts them, without slowing the fast one

Built:

- `Settings` is a frozen Pydantic model; `Settings.from_env()` maps
  `DOD_<NAME>` to each field and raises `SettingsError` listing every bad
  variable. Beyond the plan: an unknown `DOD_` variable is an error with a
  "did you mean" hint, `nan`/`inf` are refused, `COM3` gets a hint about the
  Windows bridge. A test checks the table in backend.md 11 against the code.
- `create_app(settings=None)` reads the environment when no settings are
  given; a bad value prints the message and exits with 1, no traceback.
  `./dod backend` checks the settings once before uvicorn starts (with
  `--reload`, a failing app would leave the reloader hanging), and the
  wrapper now passes every `DOD_` variable from the shell into the container.
- left for step 4: `sim?…` options and the LED count's upper limit are
  checked when the hardware is created (only `hardware.py` imports `hcl`).
- the bus: events in `dod/bus.py` with the fields the later steps need
  (`by`, `reason`, …); `Subscription` with `dropped`, `take_all()`, `close()`
  and `with`; `Bus.close()` for shutdown.
- found on the way: tech-spec 6.3 mounted the songs at `/app/cache`, the
  default is `/work/cache` (the image's working directory); fixed in the
  tech-spec.
- 60 backend tests, 0.7 s.

### Step 3. Engine core (backend.md 7.2, 7.3)

Files: `dod/engine/picture.py`, `output.py`, `matrix.py`,
`effects/base.py`, `effects/solid.py`, `effects/rainbow.py`, `effects/idle.py`

- `Picture`, `Context`, `Effect`, `Param` (slider, color, choice, toggle)
- `output.apply()` in the order of backend.md 7.3: master brightness → flash
  limit → power limit (scaling before gamma) → preview → gamma → integers;
  it returns both the LEDs' output and the preview
- the flash limit exactly as defined in backend.md 7.3 (level, transition,
  6 transitions per 1 s window, previous frame repeated), for the strip and
  the 8x8 separately
- the first three effects, enough to see something: solid colour (with a
  fade), rainbow, idle
- 8x8 helpers: draw an icon from a bitmap, bars from values

Done when:

- [x] every effect, for 1, 10 and 60 LEDs, with every parameter at its minimum,
  maximum and default, gives a picture of the right shape; same context →
  same picture
- [x] at most 6 transitions in any 1 s window, also for a strobe at 20 Hz
  (strip and 8x8); a 2 Hz on/off passes unchanged
- [x] the power limit holds exactly for full white, measured after gamma;
  gamma keeps 0 and 1 where they are; the preview is the picture before gamma,
  already dimmed by the power limit
- [x] engine tests import nothing from `hcl`

Built:

- `OutputStage(brightness, power_limit_ma).apply(picture, now)` returns
  `Output(hardware, preview, strip_held, matrix_held, power_scale)`; the loop
  sends `out.hardware` (backend.md 7.1 updated from `out.leds`). It keeps the
  flash limit's history, so there is one per render loop.
- `FlashLimiter` implements the definition from backend.md 7.3; a change of
  exactly 0.2 counts despite float rounding. The tests check its output with a
  separate count of on/off changes, not with the limiter itself.
- beyond the plan: a 100 ms beat flash at 120 BPM and flicker below the 0.2
  step pass untouched; the strip and the 8x8 are limited independently;
  matrix brightness that rounds to 0 sends the pixels all off (the MAX7219
  still glows at its lowest setting); while the power limit is on, the
  integers are rounded down so they can't exceed it.
- every effect with every parameter sample runs 5 s through `OutputStage`
  without ever being held, so none of them needs the safety net.
- the effects: `solid` (colour, optional fade to a second colour), `rainbow`
  (speed, width, saturation, direction), `idle` (not pickable). Their 8x8
  pictures are placeholders until the 8x8 decision in step 7. `matrix_icon`
  from the old design example is gone: the effect draws the 8x8 itself.
- added `dod/engine/color.py` (hex, HSV, mix, luminance) and
  `dod/engine/effects/__init__.py` with `EFFECTS` and `PRESETS`.
- 239 backend tests, ~1 s.

### Step 4. The HCL seam and the render loop (backend.md 5, 7.1)

Needs: step 0.

Files: `dod/hardware.py`, `dod/engine/loop.py`; lifespan wiring and
`GET /api/status` in `dod/main.py` (moved into `api/http.py` in step 6)

- `Hardware`: start / stop, `led_count`, `show()` (Picture → `hcl.Frame` →
  `submit`, never raising – also not on a stopped link), `status`, the events
  task (HCL events → bus, backend.md 5.5), the status poller
- the render loop: fixed 30 fps timestep, the effect → output → hardware,
  a hook for the preview every 3rd tick; an effect that throws shows black for
  that tick, 10 in a row switch to idle. State comes in step 5, so for now the
  loop runs a fixed rainbow.
- the lifespan from backend.md 4.1, including the task supervisor that
  restarts a crashed task, and the internal URLs printed at startup
- `GET /api/status`

Tests use `hcl.testing.sim_link()`.

Done when:

- [x] with `./dod backend`, the simulated board shows the rainbow (seen in a
  test through `board.strip_rgb()`, and in `/api/status`: connected,
  ~30 fps)
- [x] `board.unplug()`: `BoardLost` on the bus, the render loop keeps running;
  `board.replug()` shows the picture again
- [x] the LED count follows the board's HELLO (a simulated board with 12 LEDs
  gets 12-LED frames)
- [x] a broken effect doesn't stop the loop; a crashed task is restarted
- [x] the loop keeps 30 fps (±1) over 3 s while the tests run

Built:

- `dod/hardware.py`: `Hardware` (as in backend.md 5.1), `HardwareStatus`
  with `for_pages()` and `same_for_pages()` (the state is broadcast only when
  state, simulated or error change), `check_settings()` and `open_link()`.
  `main.py` can't import `hcl`, so it gets the link from `hardware.open_link()`
  and tests pass theirs with `create_app(settings, link=…)` – backend.md 5.1
  corrected.
- `settings_or_exit()` also runs `hardware.check_settings()`: a bad `sim?`
  option or more than 167 LEDs stops the backend with the same kind of message
  as the other settings, also in `./dod backend`'s check before uvicorn.
- `dod/engine/loop.py`: `RenderLoop` with a `Scene` (effect, params, start
  time, drawing); `set_effect()` restarts the effect's time, `set_params()`
  doesn't, so a rainbow doesn't jump when a slider moves. Missed slots are
  skipped (tested with a 250 ms stall: no catch-up burst). `on_preview` every
  3rd tick, `on_fallback` when it falls back to idle.
- `dod/tasks.py`: `Supervisor` restarts a task that crashes or ends.
- `/api/status`: `{"link", "render", "tasks"}` (backend.md 5.6 updated).
- the real log: `dod` and `hcl` loggers next to uvicorn's, at
  `DOD_LOG_LEVEL`; board connects, losses, warnings and the boot text show up
  there, and the internal URLs at startup.
- the simulated board only sends LOG messages about bad frames, which the link
  never lets through, so `BoardLog` is tested by feeding `handle_event()` the
  HCL's public `DeviceLog` event.
- checked by hand: `./dod backend` → `/api/status` from Windows PowerShell:
  connected, 30.0 fps, ~4 ms round trip; render 30.5 fps.
- 269 backend tests, ~10 s (the timing tests are most of it); three runs in
  a row green.

### Step 5. State, sessions and the queue (backend.md 6, 8)

Files: `dod/state.py`, `dod/control/queue.py`, `dod/control/sessions.py`

- the `State` from backend.md 6 with change notifications, the mode rules
  (manual / music / idle), and the server's `now` in what is broadcast
- the queue as pure logic with an injected clock: every rule from backend.md 8
- sessions: creating and reading the `dod_session` cookie, the internal key
  check (constant time)

Done when:

- [x] every queue rule has a test with a fake clock: turn length, the 3
  minutes end a turn only when someone waits, their song's end ends the turn,
  a song from the previous turn doesn't end the new one, rejoining at the
  back, a reload keeps the place, admin skip / pause
- [x] inactivity: no command for 30 s, or disconnected for 30 s, loses control
  **also when nobody waits**; a song they started keeps them active while it
  plays; a reload within 30 s keeps control
- [x] state changes notify once per change; mode switches follow backend.md 6
- [x] idle mode starts `DOD_IDLE_SECONDS` after control was released and
  nothing plays

Built:

- `dod/control/queue.py`: `Queue` as in backend.md 8; every changing call
  returns its bus events. Decided while building (backend.md 8 updated): a
  song ending with nobody waiting makes the turn *over* like the 3 minutes,
  and it ends when someone joins; their own song keeps them active also when
  offline (phone locked while watching); offline time from before the turn
  doesn't count; a waiting visitor offline for 30 s leaves the queue
  (`QueueLeft(reason="gone")`, new field); `song_stopped()` for a song
  replaced by a preset or another song, which ends no turn; paused time is
  added to the turn on resume. Offline times are only kept for sessions in the
  queue, so nothing piles up during the day.
- `dod/control/sessions.py`: tokens, the **public id** (SHA-256 of the
  token, 12 hex characters; screens show 4), cookie options, the constant-time
  key check. The queue, the state and the logs never see a token (backend.md
  9 updated).
- `dod/state.py`: `State` with the modes, parameters remembered per preset,
  the drawing, songs (`song_started` / `song_ended(reason)` for the player in
  step 8), the queue commands, `tick()`, `to_dict()` with `title` and
  `turn_over` added, `you(who)`, `may_control(who)`. Listeners hear of a
  change once, and only when the state's signature really changed.
- wired in the lifespan: the queue clock task (4 / s); the hardware status
  into the state; `SceneSync` makes the render loop follow the state (a new
  effect restarts at t = 0, new params don't); the loop's fallback to idle
  tells the state. The stand now starts in idle instead of the rainbow.
  Music mode shows the rainbow until the music effect exists (step 8).
- the render loop shows the visitor's drawing instead of the effect's 8x8
  (`set_drawing()`).
- found and fixed: the idle countdown started at the last tick that still
  had a controller instead of the tick where control was lost.
- 329 backend tests, ~11 s.

### Step 6. The API (backend.md 9)

Files: `dod/api/messages.py`, `dod/api/ws.py`, `dod/api/http.py`

- every message from backend.md 9 as a Pydantic model; unknown or malformed →
  `error: invalid`; the error codes from backend.md 9
- the hub: connections with their role and session, `welcome`, `state`
  (≤ 20 / s), `you`, `preview` (10 / s), `log`
- the close codes: `4401` without a session cookie, `4403` without the key,
  `4001` for the older `main` when a new one connects
- permissions (who may send what), the per-phone rate limit
- HTTP, as in backend.md 9: the page routes (placeholder page until the
  frontend exists), `/api/session`, `/api/status`, `/api/songs` (empty list
  until step 8)
- the JSON Schema of all messages written to `src/backend/schema/messages.json`
  for the frontend, and a test that fails when it is out of date

Done when:

- [x] with `TestClient`: a phone calls `/api/session`, joins the queue, gets
  control, picks the rainbow, and every connection gets the new state and
  previews
- [x] a WebSocket without the cookie is closed with `4401`; `main` and
  `logging` without the key with `4403`; a second `main` closes the first with
  `4001`
- [x] a phone that isn't in control gets `not_your_turn`
- [x] a flood of commands from one phone is cut at ~20 / s; a 100 kB message
  closes the connection
- [x] the schema file is generated and checked

Built:

- `dod/api/messages.py`: every message from backend.md 9 as a Pydantic model,
  in both directions; incoming ones refuse unknown fields; `parse()`.
- `dod/api/schema.py` + `./dod schema` → `src/backend/schema/messages.json`.
  Incoming messages in validation mode, outgoing ones in serialization mode
  with every field required, so the generated TypeScript gets `type` as a
  required discriminator instead of `type?`.
- `dod/api/ws.py`: `Hub` – connections with role and session, a writer task
  and a 64-message queue per browser (a slow phone drops its oldest), state
  broadcast coalesced to ≤ 20 / s, `you` only when it changes for that
  browser, previews serialized once for everyone, `send_log()` for step 9,
  permissions, a token bucket per phone (20 / s), the close codes, two tabs of
  one phone counted as one visitor. Hooks for step 8: `play_song`,
  `on_spectrum`, `on_player`, `songs`.
- `dod/api/http.py`: the placeholder pages, `/api/session[?key=]`,
  `/api/status` (moved from `main.py`, now with the number of connections),
  `/api/songs` (empty), `/api/health`.
- decided while building (backend.md 9 updated): the internal cookie is set
  by `/api/session?key=…`, `HttpOnly`, instead of by page script; error code
  `forbidden` for messages a role may never send; close codes `4400` (bad
  role), `1009` (over 64 kB, checked by the app itself too, not only by
  uvicorn), `1001` (shutdown).
- checked by hand against `./dod backend` with a real WebSocket client:
  cookies from `/api/session`, welcome → state → you, a phone's preset seen
  by the main screen, a 100 kB message closed with 1009, the main role without
  the key closed with 4403.
- 388 backend tests, ~16 s; three runs in a row green.

### Step 7. The presets (backend.md 7.2, 7.4)

Needs: what the 8x8 shows in manual mode – left to me, decided while
building it (tech-spec 5.3).

Files: `dod/engine/effects/fire.py`, `police.py`, `breathe.py`, `comet.py`,
`strobe.py`; icons and animations in `dod/engine/matrix.py`

- the remaining presets, each with its parameters in Slovak (`Rýchlosť`, …)
- the 8x8 in manual mode as decided, and the visitor's drawing
- tech-spec 5.3 updated with the decision

Done when:

- [x] all presets pass the step 3 effect tests
- [x] the strobe stays within the flash limit at every speed setting
- [x] the drawing reaches the simulated board's 8x8 unchanged

Built:

- five presets, in the phone's order after the rainbow: `fire.py` (Oheň:
  speed, wildness, palette fire / blue / green; every LED flickers on its own
  phase, a sum of sines, so it is deterministic and the strip's average hardly
  moves), `police.py` (Polícia: the halves take turns, at most 2 swaps a
  second, the other half dimmed to 6 %, not off; red and blue or amber; with
  red and blue the strip's average stays almost the same), `breathe.py`
  (Dýchanie: colour, 0.1–0.8 breaths a second, lowest brightness),
  `comet.py` (Kométa: colour, 0.2–1.5 passes a second – passes, not LEDs, so
  a long strip doesn't make it race – tail 1–6 LEDs, direction; a white head
  fading into the colour), `strobe.py` (Stroboskop: 0.5–2 flashes a second,
  0.1 s each, colour; the flash limit is 3, the preset stays under it on its
  own). `Solid` is last in the order now ("Farba"); the rainbow stays the
  first preset.
- the 8x8, decided (tech-spec 5.3): an icon per preset, animated where it
  makes sense; the drawing replaces it. `matrix.py` gets the icons (rainbow,
  flame, lightning, drop; the old placeholder square is gone) and `ring()`,
  `outline()`, `overlay()`.
- tests: every preset, every parameter extreme, 1/10/60 LEDs (the step 3
  tests: 729 backend tests now, most of them these cases); the strobe at
  every step of its slider (0.5 to 2.0), at 1, 10 and 60 LEDs, 10 s each,
  never held by the flash limit; it flashes exactly `rate` times a second for
  ~0.1 s; police keeps the strip's average within 0.1 when it swaps; every
  preset's 8x8 differs from the others' and the animated ones move; a drawing
  reaches the 8x8 unchanged over every preset, frame after frame
  (`test_loop.py`), and on the simulated board (`test_app.py`, from step 6).
  Letting the strobe go to 3 flashes a second makes two tests fail.
- checked by hand against the running backend: a phone picks each preset,
  the render loop runs it at 30 fps, the previews show the strip moving
  (police and strobe: two pictures, as designed) and the icon on the 8x8.
- `./dod schema` rewrote `presets.json`; the phone shows the new presets with
  no frontend change, as designed.

### Step 8. Music (backend.md 6, 7.4; tech-spec 5.2)

Needs: the song list, from you.

Files: `dod/music/songs.txt`, `library.py`, `download.py`, `audio.py`,
`player.py`, `dod/engine/effects/music.py`; `/media/<id>.mp4` in `http.py`

- `yt-dlp` (pinned), `ffmpeg` (apt) and `deno` (copied from
  `denoland/deno:bin-<version>`, pinned) in the image
- `songs.txt`: one YouTube link per line, an optional short title after it
  (YouTube's own titles are too long for a phone)
- `./dod songs` downloads what is missing (max ~7 min, a format every browser
  plays: H.264 video with AAC audio, ≤ 720p), with title and length next to
  each file
- the library: which songs are on the list, which are downloaded;
  `/api/songs`
- the player, as in backend.md 6: `play_song` refused with `no_player` without
  a main screen; a song ends on `player.ended`, at `started_at + length + 10 s`,
  or after 10 s without a `player` message; then back to the last preset; a
  song keeps playing when the turn ends; `music.player_connected` in the state
- the queue gets `song_started` / `song_ended` from the player
- audio: the latest spectrum, stale after 200 ms (fades out instead of
  freezing), `DOD_AUDIO_DELAY_MS`
- the music effect: spectrum → strip, 8 bars on the 8x8
- `/media` with range requests, so the video can seek (**verify** that
  Starlette's `FileResponse` answers `Range` with 206, or add it); the id is
  checked against `^[A-Za-z0-9_-]{11}$` and the song list before it touches
  the file system

Done when:

- [ ] `./dod songs` downloads the list into `cache/`, a second run downloads nothing
- [ ] a test song (a short generated clip, not from YouTube) is served with
  range requests; `../etc/passwd`-style and unlisted ids get 404
- [ ] a spectrum sent over the WebSocket changes the simulated board's picture
  within 2 frames; no spectrum for 200 ms fades it out
- [ ] each of the three song endings returns to the preset; the controller's
  own song ending ends the turn (if someone waits); `no_player` without a
  main screen

### Step 9. The fake logs (backend.md 10, tech-spec 4.5)

Files: `dod/logs/generator.py`, `dod/logs/templates.py`

- real events from the bus become lines; filler from templates; bursts on
  `LoadingStarted` and `SongStarted`, at most one every 3 s
- real numbers from the hardware status and the engine
- the last 300 lines kept, sent in batches to `main` and `logging` only

Done when:

- [x] with a fixed seed and a fake clock: calm rate 3–8 lines / s, bursts 30–50
  lines in ≤ 2 s; `loading_started` sent 10 times a second still gives one
  burst per 3 s
- [x] every template fills in without errors; real events show up within a
  second
- [x] a logging page that connects gets the last 300 lines first
- [x] phones never get `log` messages

Built:

- `dod/logs/templates.py`: what the lines say. `event_lines()` for every bus
  event (`BoardText` and `BoardIncompatible` stay out: they are real
  problems), 30 filler templates (8 with real numbers, the rest made up),
  `burst()` (a header, modules loading, progress bars, self-tests, "ready").
  `Facts`: the real numbers, read 20 times a second.
- `dod/logs/generator.py`: `LogGenerator` – when lines are written.
  `step(now)` does one moment without waiting, so the tests drive it with a
  fake clock and a fixed seed; the `log generator` task calls it every 50 ms
  (≤ 20 batches a second). Filler: every second 3–8 lines, one in each equal
  slice of it; it pauses during a burst; a stalled process doesn't catch up.
  Bursts: 1.0–1.8 s, at most one every 3 s, a trigger in between is dropped.
  The last 300 lines in `history()`.
- the hub: `Hub(..., log_history=)` sends the history right after `you`, to
  `main` and `logging` only, before any new line.
- `dod/main.py`: the generator subscribes right after the bus is created, so
  the board's first `BoardConnected` makes it in; `log_facts()` reads the
  numbers (the render loop's frame counter, bytes sent, both fps, round trip,
  the last frame for hex dumps, mode, preset, connections, queue length).
- decided while building (backend.md 10 updated): the levels are `DEBUG`,
  `INFO`, `OK`, `WARN` (a `Literal` in `LogLine`, so the schema has them; a
  board's `ERROR` shows as `WARN`); a parameter or the drawing gives at most
  one line per 0.5 s, with the latest value (a dragged slider sends 20 a
  second); board text is cut to one line of ≤ 120 characters; `Facts.beat`
  is `None` until step 8, and the `fft` line waits for it.
- checked by hand against `./dod backend` with a real WebSocket client: a
  logging page gets welcome → state → you → log (history), 142–159 lines in
  8 s with a burst, a phone joining shows up as `enqueued` and `acquired
  control` at once, `loading_started` from the phone starts a burst, the phone
  gets no `log`.
- 414 backend tests, ~19 s (was ~16 s; the new ones take ~3.5 s, half of it
  waiting for the running app's lines); three full runs in a row green.

### Step 10. End to end and soak

Files: `src/backend/tests/test_end_to_end.py`, `src/backend/tests/soak.py`

- the whole app with `DOD_SERIAL=sim`, a main screen and several phones
  connected: queue, turns, presets, a song with a spectrum, the logs
- the soak test (`./dod backend-soak --minutes 30`): random commands from
  8 simulated phones, the simulated board unplugged now and then, the main
  screen closed and reopened now and then

Done when:

- [ ] the end-to-end test passes in `./dod test`
- [ ] 30 minutes of soak: no errors in the log, memory stable (±10 MB), the
  render loop at 30 fps (±1) throughout
- [ ] the backend's test suite runs in under 30 s
- [ ] [../backend.md](../backend.md) is updated wherever the build showed the
  design had to change

---

## Order and dependencies

| Step | Needs |
|---|---|
| 0. `hcl.testing` | – (HCL only) |
| 1. Tooling | – |
| 2. Settings, bus | 1 |
| 3. Engine core | 2 |
| 4. HCL seam, render loop | 0, 3 |
| 5. State, queue | 2 |
| 6. API | 4, 5 |
| 7. Presets | 3; only its last check (the drawing on the board) needs 6 |
| 8. Music | 6 |
| 9. Logs | 6 |
| 10. End to end | all |

- 0 can be done any time before 4, also in parallel with 1–3.
- 5 can be built while 3 and 4 are.
- 7 (presets) only needs the engine core, so it can wait for the 8x8 decision
  without holding anything else up.
- 8 (music) needs the API, because the spectrum comes over the WebSocket; the
  song list can arrive any time before it.
- After step 6 the WebSocket protocol and its schema exist, so **the frontend
  plan can start in parallel** with steps 7–10.
