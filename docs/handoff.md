# Handoff – 2026-11-05

Where the build stands at the end of the day, and what to do next.
Details are in [plans/backend.md](plans/backend.md),
[plans/frontend.md](plans/frontend.md) and [plans/hcl.md](plans/hcl.md)
(each finished step has a "Built" note or a status list) and the design in
[backend.md](backend.md) and [tech-spec.md](tech-spec.md).
`./dod --manual` has every command and the full commands that launch the app.

## Where things stand

- **HCL stage 1:** done. **Stage 2 (board on the desk): done** except the
  hand checks of the board's behaviour (below). The board runs
  `src/hcl/esp/` on MicroPython v1.13; wiring checked by eye, 66 fps, all
  256 byte values pass both ways. **Stage 3 (the notebook): written, not run
  on Windows yet** – `start.bat`, `windows/start.ps1`,
  `src/hcl/bridge/serial-bridge.ps1`, and the notebook's self-contained
  image (the Dockerfile's `notebook` stage, `./dod notebook` to try it here).
- **Backend: steps 0–10 of 10 done.** The 30-minute soak passed: no
  errors, 30 fps every second, the board unplugged 19 times, memory up
  4.0 MB (54.3 → 58.3, in steps with flat stretches – watch it in the
  2-hour rehearsal soak).
- **Frontend: steps 1–7 of 8 done.** All three screens are real: `/` the
  phone, `/internal/main` the notebook's screen (with the player),
  `/internal/logging` the terminal alone. Step 8 (end to end, by hand) is
  left.
- **Tests:** `./dod test` is green – HCL 166 tests (~23.5 s), backend 794
  (~23 s, with the end-to-end test), frontend 188 (~3.6 s, plus the type
  checks). Each suite is under its 30 s budget, the HCL one closest.
- **Songs:** all 10 from `songs.txt` are in `cache/`.
- **Git:** `dod2026/` is its own repo (branch `main`, no remote yet).

| Part | State |
|---|---|
| HCL stage 1 (no hardware) | done |
| HCL stage 2 (the board) | done, hand checks of the board's behaviour left |
| HCL stage 3 (notebook, bridge) | written, not tested on Windows |
| Backend steps 0–10 | done |
| Frontend steps 1–7 | done |
| Frontend step 8 (end to end) | by hand, not started |
| Phase 5 (show polish), phase 6 (rehearsal) | not started |

## What to do next

1. **Try the notebook image here:** `./dod notebook` (builds it, a few
   minutes the first time), then http://localhost:8000 and
   http://localhost:8000/internal/main?key=dev. Not run yet.
2. **The board's behaviour, by hand** (HCL stage 2, item 5): unplug and
   replug; press EN; stop the backend (idle animation after 3 s); hold BOOT
   after EN (stays at `>>>`); `./dod esp upload` afterwards.
3. **The whole app on the real board:** `./dod dev` with the board attached
   – presets, a song, a phone's drawing on the real strip and 8x8. Never
   done yet; also backend step 7's last check.
4. **The bridge on this PC, before the notebook:** `usbipd detach` the board
   so Windows sees it as COMx, then `start.bat` (if Docker Desktop is here)
   or the bridge alone in Windows PowerShell. Check both scripts parse first.
   Open: whether the container reaches the bridge on Windows' `127.0.0.1`
   (if not, the bridge's `-Listen 0.0.0.0`, with the firewall closing 7777
   to the hotspot), and whether the hotspot's password can be read without
   admin rights (`-WifiSsid/-WifiPassword` otherwise).
5. **The hand checks in a browser** – the list in plans/frontend.md, steps
   1–7 ("by hand"), then frontend step 8 with two real phones. Real phones
   need WSL's mirrored networking first (`./dod --manual`, 1.6).
6. **On the notebook** (HCL stage 3, steps 2–4): Docker Desktop, `start.bat`,
   `./dod hcl bench` through the bridge, container restarts, unplugging.
   The riskiest part of the project – as soon as the notebook is available.

Still waiting on: the hotspot's name and password (for the Wi-Fi QR code;
`start.bat` reads them from Windows), an Android phone and an iPhone.

## How to pick up

```sh
cd ~/spseke/dod2026
./dod --help               # every command; ./dod --manual explains them all
./dod test                 # all three suites; ./dod test backend -x for one
./dod sim                  # backend + Vite: http://localhost:5173, simulated board
                           # internal pages: /internal/main?key=dev
./dod dev                  # the same with the board (usbipd attach --wsl --busid <id> first)
./dod notebook             # the notebook's image, here, on http://localhost:8000
./dod backend-soak         # 30 min soak; --seconds 120 for a quick try
```

- **In Claude Code, `./dod` must run outside the sandbox** (Docker's socket
  is blocked inside it). `./dod --help` and `--manual` work anywhere.
- `./dod build` builds the dev image (`--target dev`); a plain
  `docker build .` builds the notebook image.
- Any `DOD_*` variable in your shell reaches the container, e.g.
  `DOD_BRIGHTNESS=0.3 ./dod sim`.
- Quick look at a running backend: `curl localhost:8000/api/status`.

## Built today

- **The music light show, redesigned** (backend.md 7.5). The kick detector
  was broken on real music – it compared dB values against 1.4× their
  average and found 4–38 kicks in a whole song; it is now spectral flux and
  finds most of them. The backend also finds snares, hi-hats, calm parts,
  builds and drops, and the strip is layered from them: a moving colourful
  base held at a steady brightness, kick hits in 5 shapes, snare flashes,
  hi-hat glints, a riser in builds, a white hit and a new scene at drops.
  The 8x8's bars now fall slowly. Checked offline on all 10 songs (their
  spectra computed the way the browser does): no frame held by the flash
  limit. **To do: watch it on the real strip** (`./dod dev`, play Sandstorm
  and L'Amour Toujours – both have a breakdown, a build and a drop).
- **Each song's light show under the video** (backend.md 7.6): `./dod songs`
  works out `<id>.show.png` (the strip over the whole song) for every
  downloaded song, new or with a stale one; the main screen shows it with a
  playhead. All 10 songs have theirs. numpy is a new backend dependency:
  **`./dod build` and rebuild the notebook image**. After changing the show,
  run `./dod songs` again (old pictures aren't served).
- **`dod.bat` on Windows** (`windows/dod.ps1`): the same commands as
  `./dod`, in Docker Desktop. The board goes through the serial bridge
  (Docker Desktop can't pass a COM port in): `DOD_SERIAL=COM5` / `board`,
  `ESP_PORT=COM5`; the esp commands use mpremote over `socket://`. The
  backend and Vite poll for file changes there. Shared helpers moved to
  `windows/common.ps1` (start.ps1 uses them too). Checked with Windows
  PowerShell 5.1 on this PC: all scripts parse; `--help`, `--manual`,
  argument passing (quotes, `-k`, `-x`), exit codes. **Not run with Docker
  Desktop yet** – do `dod test`, `dod sim`, `dod songs`, and with the board
  `dod hcl bench`, `dod esp upload` on the notebook. `tests/test_launchers.py`
  fails when `./dod` and `dod.ps1` get different commands.
- `./dod notebook` now passes every `DOD_*` setting (the manual's
  `DOD_AUDIO_DELAY_MS=200 ./dod notebook` did nothing before).
- `test_ws.py`'s flood and log-order tests fail on battery (the CPU is
  throttled ~3×; they fail with the code before today too) – run the suites
  on mains power.
- **HCL stage 2 committed** (the board's code, `./dod esp`, the late-HELLO
  fix in the link). Pytest no longer walks into `esp/` and `esp_tests/`
  (MicroPython, they import `machine`).
- **Backend step 10:** `tests/test_end_to_end.py` (a round of the day through
  the whole app) and `tests/soak.py` (`./dod backend-soak`).
- **The Windows side** (tech-spec 6.3, hcl.md 8):
  - `serial-bridge.ps1` waits on both reads at once (`ReadAsync` +
    `WaitAny`): polling with `Start-Sleep` sleeps ~15 ms on Windows and
    would cost the 30 fps. A new client replaces the old one; the COM port
    stays open between clients; .NET's finalizer crash on unplug is
    suppressed; `-ParentPid` stops it with the launcher.
  - `start.ps1`: Docker Desktop, the board by USB id (CP2102, CH340,
    CH9102), the bridge, the image, the hotspot's address, name and
    password, a random key, the container, Edge full screen with its own
    profile (so closing it is noticed), cleanup; leftovers of a crashed run
    are removed at the next start. Logs: `%TEMP%\dod2026\`.
  - All `.ps1` files are ASCII (Windows PowerShell 5.1 reads them in the
    local code page); `.gitattributes` keeps `.bat`/`.ps1` in CRLF.
- **`./dod --help`, `./dod --manual`**; `DOD_SERIAL=/dev/ttyUSB0 ./dod notebook`
  passes the board in.

## Loose ends worth knowing

- **HCL suite ~23.5 s** – close to its 30 s budget.
- When the board's LED count changes, the flash limiter starts its count
  over, so across that one moment up to 12 transitions could fall into one
  second. Rare (a different board); not in backend.md yet.
- `SceneSync` (state → render loop) lives in `dod/main.py`; it may want its
  own module as the music and drawing logic grow.
- The frontend's tests print "Web Audio failed" traces: expected, jsdom has
  no `createMediaElementSource`; the player logs it and carries on.
- The dev image installs `mpremote` and `esptool` unpinned.
- Still **(verify)** in tech-spec and hcl.md: the bridge's speed through
  Docker Desktop and the container reaching `127.0.0.1`, reading the
  hotspot's password, the hotspot's 8-device limit, phones on a Wi-Fi
  without internet.
