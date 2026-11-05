# DOD 2026 – technical spec

How the project is built, run and developed. What the project *does* is in
[dod.md](dod.md). Status: **settled**. Items marked **(verify)** are assumptions
to test on the real hardware and notebook (phases 3 and 4 in the plan). Items marked
**(open)** still need an answer, see [Open questions](#open-questions).

## 1. Overview

```
 phones / main screen (browser)                 notebook (Windows)                       ESP32
┌─────────────────────────────┐   Wi-Fi /   ┌──────────────────────────────┐         ┌──────────────────┐
│ web UI (Slovak)             │   LAN       │ Docker container             │  USB    │ MicroPython      │
│  - music mode (video + FFT) │◀──────────▶│  FastAPI + render loop       │  serial │  bridge only:    │
│  - manual control / presets │  HTTP + WS  │  effects, presets, fake logs │◀──────▶│  strip, 8x8      │
│  - fake logging terminal    │             │  yt-dlp song cache           │         └──────────────────┘
└─────────────────────────────┘             └──────────────────────────────┘
```

- **All logic is on the backend.** It decides every LED colour and every 8x8
  pixel, and sends them to the ESP32 as frames. It also writes the fake logs,
  which the notebook's screen shows as a terminal (section 4.5).
- **The ESP32 is a dumb bridge.** It receives frames over serial and pushes
  them to the peripherals. Its only logic is the fallback idle animation it
  shows when the backend stops talking ([hcl.md](hcl.md), section 7.2).
- **The HCL is the only part that talks to hardware.** The backend hands it
  finished frames; how they reach the board (serial, the Windows bridge, or a
  simulated board) is hidden behind it. Design in [hcl.md](hcl.md).
- **One process, one source of truth.** The backend holds the current state
  (mode, preset, parameters) and broadcasts it to every open browser over a
  WebSocket, so all screens always show the same thing.

## 2. Hardware

| Part | Bus | ESP32 pins (proposed) | Notes |
|---|---|---|---|
| addressable RGB strip, 10 LEDs, unmarked – assumed WS2812B | 1 data wire | GPIO15 (wired; 13 was proposed) | 5 V, see power below |
| 8x8 single-colour LED matrix, MAX7219 module (chip marked `MAX7219ENG`) | SPI-like: DIN, CLK, CS | DIN 21, CLK 18, CS 19 (wired; hardware SPI routed there, its MISO moved to the free GPIO39) | runs on 5 V, write-only, 16 brightness levels |

The 8x8 module is **not I2C**: the MAX7219 has no I2C interface. It takes 3 signal wires (DIN, CLK, CS) and is driven with
`machine.SPI`. `ENG` on the chip usually means a clone or an engineering
sample – they normally work, but if the matrix shows random pixels or resets,
that is the first suspect, and spare modules are cheap.

The strip has no markings. With 3 wires (5 V, DIN, GND) it is almost
certainly WS2812B or a clone; the colour order (GRB or RGB) is a setting in
`src/hcl/esp/config.py`, found with `./dod hcl pattern`.
4 wires (with a CLK) would mean APA102/SK9822, which needs a different driver.

There is no LCD: the logs are shown on the notebook's screen instead
(section 4.5).

Things to get right on the hardware side:

- **Power: a separate 5 V supply** (5 V / 2–3 A adapter) for the strip and
  the matrix; the ESP32 stays on USB. Full white on 10 LEDs is 600 mA, and a
  MAX7219 matrix with everything lit at full brightness draws a few hundred
  more. Together with the ESP32 that is well over the 500 mA a USB port gives. Don't connect the adapter's 5 V to
  the board's 5 V pin while USB is plugged in (they would feed into each
  other). Ground is shared between everything. A 470–1000 µF capacitor across
  the strip's power input, a ~330 Ω resistor in the strip's data line.
- **3.3 V signals, 5 V power – safe for the ESP32.** The strip and the
  matrix are powered from the 5 V supply, and their signal pins are driven
  straight from the ESP32's 3.3 V GPIOs. This cannot damage the ESP32: the
  signals only go *from* the ESP32 *into* the strip and the MAX7219, whose
  inputs take almost no current and never push 5 V back. What would damage
  it is 5 V *on* an ESP32 pin, so:
  - the matrix is connected on its **input** side (the header with **DIN**).
    The other side's DOUT is for chaining more modules and stays unconnected.
  - the supply's 5 V goes only to the strip's and the matrix's VCC, never to a
    GPIO, and not to the ESP32's 5 V pin while USB is plugged in
  - the grounds are connected, or the signals have no reference and nothing
    works

  The catch is reliability, not safety: powered from 5 V, the WS2812B and the
  MAX7219 officially want ≥ 3.5 V for a logic high, and 3.3 V is just under.
  With short wires it works in most builds (this is the usual hobby
  wiring). If the 8x8 shows random pixels or the strip flickers in phase 3:
  first lower the SPI clock (1 MHz is plenty for 8 rows) and shorten the
  wires; if that does not help, add a 74AHCT125 between them (4 channels:
  strip data, DIN, CLK, CS – its VCC on 5 V, its `OE` pins on GND).

  Wiring overview:

  ```
  5 V supply + ──┬──────────── strip 5V
                 └──────────── matrix VCC
  ESP32 GPIO15 ── 330 Ω ────── strip DIN
  ESP32 GPIO21 ─────────────── matrix DIN   (input side of the module)
  ESP32 GPIO18 ─────────────── matrix CLK
  ESP32 GPIO19 ─────────────── matrix CS
  ESP32 GND ── 5 V supply − ── strip GND ── matrix GND
  1000 µF across strip 5V / GND, as close to the strip as possible
  ESP32 itself: powered over USB from the notebook
  ```
- **Only 10 LEDs.** Effects that rely on movement along the strip (comet,
  chase) have little room. The light show leans on colour, brightness and
  timing, and the 8x8 carries more of the show than planned.
- **Parts to buy:**
  - 5 V / 3 A power adapter + a DC jack or screw terminal for it
  - 1000 µF / ≥ 6.3 V capacitor, 330 Ω resistor (strip)
  - optional, only if phase 3 shows glitches: 74AHCT125
- **Brightness limit in software.** The backend estimates the strip current
  from each frame (sum of all channel values × 20 mA / 255) and scales the
  frame down if it would go over the supply's rating. This lives in one place
  (section 4.3), so no effect can overload the supply.

## 3. Repository layout

The system has three layers, each in its own folder under `src/`:

```
frontend ⇄ backend → HCL → ESP32 → strip, 8x8
```

```
dod2026/
  docs/
    dod.md               what the project does
    tech-spec.md         this file
    hcl.md               the hardware communication layer and the serial protocol
    preview.html         clickable mockup of the frontend
  Dockerfile             the one image, used for running and for development
  dod                    dev wrapper for WSL (bash), like ~/spseke/esp/setup/esp
  start.bat              Windows launcher: double-click this on the notebook
  windows/start.ps1      what start.bat actually runs
  src/
    frontend/            React frontend (Vite); its build is served by the backend
      package.json
      vite.config.ts
      index.html
      src/
        main.tsx
        api/             WebSocket client, message types
        screens/         Main, Logging (notebook), Phone, Queue
        apps/            Music, Manual
        components/      Preview (strip, 8x8), Terminal, LoadingScreen, ...
        assets/fonts/    the terminal's monospace font, bundled
    backend/             see backend.md, section 3
      pyproject.toml
      dod/               Python package "dod"
        main.py          FastAPI app; builds and wires everything
        state.py         current mode, preset, parameters, what plays
        hardware.py      the only module that talks to the HCL
        engine/          render loop, effects, presets, power and flash limits
        control/         the queue, sessions
        logs/            fake log generator for the logging page
        music/           song list, downloads, the spectrum from the main screen
        api/             HTTP routes, the WebSocket and its messages
      tests/
    hcl/                 hardware communication layer, see hcl.md
      hcl/               Python package the backend imports: link, protocol, simulated board
      esp/               MicroPython code that goes on the board
      bridge/            Windows COM port ↔ TCP bridge
      tests/
  cache/                 downloaded songs (not in git)
```

## 4. Backend

This section is the overview. The detailed design – modules, state, the
render pipeline, the queue's rules, every WebSocket message and the
connection to the HCL – is in [backend.md](backend.md).

### 4.1 Stack

- Python 3.13, FastAPI, uvicorn (**one worker** – there is one serial port and
  one state, more workers would fight over them)
- `pyserial` – it opens both real ports (`/dev/ttyUSB0`) and TCP ports
  (`socket://host.docker.internal:7777`) with the same call, which is what
  makes the Windows bridge in section 6.2 possible without extra code
- no numpy: 10 LEDs and 64 pixels are tiny, plain Python is fast enough
  (backend.md 2)
- `yt-dlp` + `ffmpeg` (+ `deno`, which yt-dlp needs for YouTube now) – music mode
- `pytest` – tests

### 4.2 Background tasks

Started on app startup, all asyncio:

| Task | What it does |
|---|---|
| render loop | ticks at 30 fps, asks the active mode for a strip frame and an 8x8 frame, applies the power and flash limits, hands the frame to the HCL with `submit()` |
| HCL events | forwards the HCL's events (board connected, rebooted, its log messages) to the log generator and the status badge |
| log generator | builds log lines from real events and templates (section 4.5) and sends them to the logging page |

### 4.3 Modes

Every mode runs an effect with the same interface, so the render loop does
not care which one is active; each effect declares its own parameters, and
the phone builds its controls from them (backend.md 7.2).

- **Music mode** – takes the latest spectrum from the browser (section 5.2),
  turns it into a light show on the strip and a spectrum bar graph on the 8x8.
- **Manual mode** – presets (rainbow, fire, police, breathing, comet,
  strobe, …), each with its own parameters (speed, colours, width, direction,
  …), plus a plain colour picker and fades between colours.
- **Idle mode** – runs when nobody does anything, so the stand never looks dead.

After the mode renders, two filters always run:

1. **power limit** (section 2)
2. **flash limit** – full-strip flashes (strobe, beat flashes) are capped at
   3 per second. Big flashing lights in front of many people is a
   photosensitive epilepsy risk; 3 Hz is the usual safe limit.

### 4.4 API

- `GET /`, `/internal/main`, `/internal/logging` – the web app (FastAPI
  answers every page route with the React app's `index.html`, React Router
  picks the screen)
- `GET /media/<id>.mp4` – a downloaded song
- `GET /api/songs` – the song list, and which songs are downloaded
- `WS /ws?role=phone|main|logging` – everything live. `main` and `logging`
  need the internal key (5.1).
  - browser → server: `{"type": "set_preset", ...}`, `{"type": "set_param", ...}`,
    `{"type": "spectrum", "bands": [32 floats], "beat": bool}`, `{"type": "set_matrix", ...}`, …
    (the full list, with who may send what, is in backend.md 9)
  - server → browser: `{"type": "state", ...}` on every change, `{"type": "preview", ...}`
    at ~10 fps (the current strip and 8x8, so the page can show them)
  - server → notebook pages only: `{"type": "log", "lines": [...]}`. Phones never
    get the log stream, it would only use up the hotspot's bandwidth.

### 4.5 The logging page (fake logs)

The left ~30 % of the notebook's screen (5.1) is a fake terminal that never
stops scrolling. English, technical looking, completely fake in
spirit – but it looks far more convincing when real things are mixed in, so
there are three kinds of lines:

- **Real events, dressed up**: a visitor joins the queue or gets control, a
  song starts, a preset or parameter changes, the ESP32 says HELLO, the serial
  link reconnects. Plus real numbers: fps, frame counter, bytes sent, detected
  beat, and hex dumps of actual frames sent to the board. LOG messages from
  the ESP32 show up here too, tagged `esp32`.
- **Filler** from templates with made-up subsystems and numbers, so the screen
  is busy even when nothing happens.
- **Bursts**: when a song starts, the mode changes or a loading screen runs,
  30–50 lines in a second or two – boot sequences, progress bars, "module
  loaded" lists. They are timed with the loading screens on the phones, so
  both look like they are doing the same heavy work.

```
[14:02:17.481] rgb-core    INFO  frame 008412 committed (36 B, sum 0x5e)
[14:02:17.495] fft         INFO  32 bins ok, peak 112 Hz, beat=1
[14:02:17.502] photon-bus  WARN  coherence drift 0.03%, recalibrating
[14:02:17.530] queue       INFO  session 7f3a… acquired control (2 waiting)
[14:02:17.611] serial      DEBUG tx a5 5a 01 1e 00 ff 00 40 9c 00 …
[14:02:18.004] lattice     INFO  matrix sync [##########----------] 52%
```

- Calm rate 3–8 lines per second, bursts up to ~40.
- Colours by level (INFO / WARN / DEBUG / OK), a different colour per
  subsystem tag, a blinking cursor, an ASCII-art banner when the page opens
  (`DOD-2026 LIGHT ENGINE v4.2.0`).
- The page keeps the last ~300 lines, older ones are dropped, so it can run
  all day without slowing down.
- Real backend errors do **not** go here – among the fake WARNs nobody would
  notice them. They go to the container's output (`docker logs`) and to a
  small status badge on the main screen.
- The generator runs in the backend (like all logic); the page only shows
  what it gets.

### 4.6 Who is in control: the queue

Visitors scan a QR code (on the main screen and the stand), the page opens on
their phone, and they wait for a turn. One person controls at a time.

- **Identity** is a random id in a cookie, created on the first visit. A
  page reload or a short phone lock keeps the place in the queue. It is not
  security – incognito mode gets a new place – it only has to be fair enough.
- **A turn** lasts 3 minutes, or until the song they picked ends, whichever
  is first.
- **The queue only matters when others are waiting.** If nobody is waiting,
  the turn just keeps going – no point kicking someone off while the stand
  sits idle.
- **After a turn**, the phone shows "Tvoj čas skončil" and a button to queue
  up again, at the back. There is no permanent lock-out: on a quiet
  afternoon the same kid can play again, at a busy moment they wait behind
  everyone else.
- **An inactive controller loses the turn**: no WebSocket connection, or no
  input, for 30 s → the next person in the queue gets it.
- **Waiting phones** show their position ("Si 3. v poradí"), roughly how long
  it is, and the live preview of the strip and 8x8.
- **The main screen** (`/internal/main`) shows the queue and the QR codes,
  plays the songs, and has hidden admin controls: skip the current person,
  pause the queue.

The whole queue lives in the backend's state, in memory. A restart of the
backend empties it, which is fine.

## 5. Frontend

### 5.1 General

- **React + TypeScript, built with Vite.** TypeScript is proposed because the
  WebSocket messages (4.4) then have types, and a typo in a message name
  shows up in the editor instead of on the day.
- Screens, picked by the URL (React Router):
  - `/` – phones: queue position, then the controls during a turn. Phones
    are only remotes – they never play video or audio.
  - `/internal/main` – the notebook's screen, split in two (below)
  - `/internal/logging` – the fake terminal alone, full screen. The same
    component as the left panel of the main screen; useful for testing it,
    or if a second monitor turns up.

**The notebook's screen** (`/internal/main`, one full-screen window):

```
┌──────────────┬─────────────────────────────────────────────┐
│ [14:02:17.4] │                                             │
│ rgb-core ... │                                             │
│ fft ...      │            video of the current song        │
│ photon-bus   │                                             │
│ queue ...    │                                             │
│ serial tx .. │                                             │
│ lattice [### ├─────────────────────────────────────────────┤
│ ...          │ ▶ song · 1:42 / 3:30 │ queue: 3 │ [QR] [QR]  │
│ █            │ strip + 8x8 preview  │ "Si na rade?"        │
└──────────────┴─────────────────────────────────────────────┘
   ~30 % width              ~70 % width
   fake terminal (4.5)       video, info bar, QR codes
```

- The left panel takes ~30 % of the width (a setting, between 25 % and 33 %).
- The right part plays the video and is the page that analyses the audio
  (5.2). Below it, an info bar: what is playing, the queue length, both QR
  codes (hotspot Wi-Fi, page address) and a small preview of the strip and
  8x8.
- When no song is playing (manual mode, or idle), the right part shows big QR
  codes, the queue, and a large preview instead of the video.
- Admin controls (skip the current person, pause the queue) open with a
  keyboard shortcut, so visitors never see them.
- **`/internal/*` is for the notebook only.** The launch script makes a random
  key on every start, passes it to the container (`DOD_INTERNAL_KEY`) and
  opens the internal pages with `?key=…`; the page keeps it in a cookie. A WebSocket
  asking for the `main` or `logging` role without the right key is refused, so
  a visitor who types in `/internal/main` gets nothing – no admin controls, and
  no way to become the music source.
- **Node never runs in WSL.** `npm` runs in a `node` container (section
  7.1), and the Dockerfile builds the frontend in a Node stage and copies only
  the finished files into the final image. FastAPI serves them; the final
  image has no Node in it.
- Everything is bundled, nothing is loaded from a CDN at runtime, so the
  manual mode works even if the school's internet is down. A QR code library
  (e.g. `qrcode.react`) draws the QR code in the browser.
- Slovak UI text, dark theme with vibrant accent colours.
- Fake loading screens: 2–4 s, never longer – the audience is the reason for
  them and has no patience. They can also hide real waiting, like a song download.
- A live preview of the strip and 8x8 on the page, fed by the `preview`
  messages. The same preview is what the simulator shows (section 7.3).

### 5.2 Music mode: why the video is downloaded

An embedded YouTube player cannot be analysed: the page has no access to its
audio, so there is nothing to compute an FFT from. Instead:

1. The songs are a fixed list in `src/backend/dod/music/songs.txt` (one YouTube
   link per line, optional title). There is no free link entry.
2. `./dod songs` downloads every song on the list that is not in `cache/`
   yet, with yt-dlp (max length ~7 min each). This is done in advance, and
   `cache/` goes to the notebook with the project; the running backend never
   downloads (decided in backend plan step 8: on the day no download competes
   with the show for the network, and a yt-dlp failure can't surface
   mid-show).
3. The visitor whose turn it is picks a song on their phone. The phone is
   only a remote: the fake loading screen runs on both the phone and the
   main screen.
4. The **main screen** plays the file from `/media/<id>.mp4` in a `<video>`
   element, on the notebook's speakers or an external speaker. It comes from
   the same server, so the browser lets the Web Audio API (`AnalyserNode`)
   read it. Phones never play audio.
5. ~30 times a second the main screen sends 32 frequency bands and a beat flag
   over the WebSocket. The backend does everything else.

**Speaker.** Notebook speakers are too quiet for a busy corridor, so an
external speaker is better – **on a cable** (3.5 mm jack or USB). The
analyser reads the audio before it leaves the computer, and Bluetooth adds
~150–250 ms on the way to the speaker, so with Bluetooth the lights would
flash *before* the beat. If Bluetooth is the only option, the backend delays
the light show by a configurable amount (`DOD_AUDIO_DELAY_MS`) to match.

Songs that are not downloaded are greyed out on the page. With a full cache,
music mode works without internet – which matters because YouTube regularly
breaks yt-dlp and the school network can block or throttle YouTube.
`cache/` is copied to the notebook along with the project. yt-dlp is pinned in
`src/backend/pyproject.toml` and updated (image rebuilt) in the week before the event,
when the songs are downloaded.

### 5.3 What the 8x8 does in manual mode

The matrix is single colour and every pixel is only on or off; brightness
(16 levels) is one setting for the whole matrix. So it shows shapes and
movement, not colours or shades. The page's preview draws it in the same
colour as the real LEDs.

**Decided (2026-11-04):** every preset shows its own icon, animated where it
makes sense, and a visitor's drawing replaces it as soon as they draw ("Ikona
presetu" on the phone brings the icon back):

| Preset | 8x8 |
|---|---|
| Dúha | a rainbow's arc |
| Oheň | a flame, with sparks flickering above it |
| Polícia | a block switching sides with the strip's halves |
| Dýchanie | a ring growing and shrinking with the breath |
| Kométa | a short comet along the diagonal |
| Stroboskop | a lightning bolt; the whole matrix lights with each flash |
| Farba | a drop of paint, emptying and filling with the fade |

These were the options:

- an icon per preset (flame for fire, siren for police, …), animated
- the strip's activity as bars: one column per LED section, height = how
  bright that part of the strip is
- **draw on your phone**: an 8x8 grid on the page, tap pixels on and off,
  they show up live on the matrix – probably the most fun one for visitors
- a face that reacts to what you do (bored when idle, shocked at max speed)
- whole-matrix brightness pulsing with the strip's fades and breathing

## 6. Running it on the notebook (Windows)

### 6.1 Prerequisites, once

The notebook is the teacher's personal one, so it should change as little as
possible, and everything should be easy to remove afterwards (6.5).

- Docker Desktop (WSL2 backend). It needs admin rights to install, a reboot,
  and virtualisation enabled in the BIOS (it usually is). This is the one big
  install – agree on it with the teacher early, and do it together.
- the USB-serial driver for the board (CP210x; Windows usually installs it by
  itself – the board shows up as `COMx` in Device Manager)
- the project folder, including `cache/`, copied to the notebook

Nothing else: the serial bridge (6.2 A) uses what is built into Windows, which
is one more reason to prefer it over usbipd.

### 6.2 Getting the serial port into the container

This is the riskiest part of the plan. Docker Desktop cannot pass a Windows
`COM` port into a Linux container (`--device COM3` does not exist). Two ways
around it:

**A. Bridge in the launch script (recommended).** `start.ps1` opens the COM
port with .NET's `System.IO.Ports.SerialPort` (built into Windows, nothing to
install) and forwards it to a TCP port on `127.0.0.1:7777`. The container
connects to `socket://host.docker.internal:7777`, and pyserial treats that like
a normal serial port. No admin rights, no usbipd, no kernel drivers in Docker's VM.
**(verify)**: throughput and latency of the bridge, and that the container
reaches a port bound to the host's `127.0.0.1`.

**B. usbipd.** Attach the board to Docker Desktop's VM with usbipd-win, like
the board is attached to WSL today, and pass `/dev/ttyUSB0` with `--device`.
Needs admin rights, usbipd installed, and the CP210x driver in Docker
Desktop's kernel. **(verify)** – fallback if A is too slow.

### 6.3 What `start.bat` does

`start.bat` only runs `powershell -ExecutionPolicy Bypass -File windows\start.ps1`
(a double-clicked `.ps1` opens in Notepad, a `.bat` runs). `start.ps1`:

1. starts Docker Desktop if it is not running and waits for `docker info`
2. finds the board's COM port by its USB ID (CP2102: `VID_10C4&PID_EA60`),
   or tells you to plug it in and waits
3. starts the serial ↔ TCP bridge (6.2 A)
4. builds the image if it is missing (`docker build -t dod2026 .`)
5. finds the notebook's hotspot address, so the main screen can show
   `http://<ip>:8000` as a QR code for phones, reads the hotspot's name and
   password for the Wi-Fi QR code, and makes a random internal key
6. `docker run --rm --name dod2026 -p 8000:8000 -v .\cache:/work/cache -e DOD_SERIAL=socket://host.docker.internal:7777 -e DOD_PUBLIC_URL=http://<ip>:8000 -e DOD_INTERNAL_KEY=<key> -e DOD_WIFI_SSID=<name> -e DOD_WIFI_PASSWORD=<password> dod2026`
7. opens `http://localhost:8000/internal/main?key=<key>` as one full-screen
   browser window (Edge is built into Windows:
   `msedge --app=<url> --start-fullscreen`). The browser may block audio until
   the first click, so the page shows a "Spustiť" button once at the start.
8. when the window is closed or Ctrl-C is pressed: stops the container and the bridge

The image is built and tested on the notebook **before** the day. Building
needs internet (pip, apt); a `docker save` of the working image on a USB stick
is the backup.

### 6.4 Network: the notebook's hotspot

Visitors' phones join a Wi-Fi hotspot made by the notebook (Windows Mobile
Hotspot), and open the page on the notebook. School Wi-Fi is not used for the
phones, so its client isolation does not matter.

- **Two QR codes** on the main screen and printed at the stand: the first
  joins the hotspot (`WIFI:S:<name>;T:WPA;P:<password>;;`), the second opens
  the page. On the hotspot the notebook's address is normally always
  `192.168.137.1`, so the second one is `http://192.168.137.1:8000`. The
  launch script still checks the real address and the page uses that one.
- **8 devices at most.** Windows Mobile Hotspot allows 8 connected devices by
  default. With the queue, that is 8 phones at once, including the person
  playing. Options: accept it (phones that have had their turn are asked to
  leave the Wi-Fi), or raise the limit with the registry value `WifiMaxPeers`
  in `HKLM\SYSTEM\CurrentControlSet\Services\icssvc\Settings` (up to 128)
  **(verify)**, if the teacher agrees to the change on their notebook.
- **Internet.** The hotspot shares the notebook's own connection, so the
  notebook stays on school Wi-Fi or a cable. Windows may refuse to start the
  hotspot with nothing to share **(verify)**. The songs are cached, so the
  project itself needs no internet.
- **Phones on a Wi-Fi without internet** may say "no internet" and try to use
  mobile data instead. Requests to `192.168.137.1` normally still go over the
  Wi-Fi, but this is checked with an Android phone and an iPhone at the
  rehearsal **(verify)**.
- **Firewall.** Windows Firewall asks to allow Docker the first time port 8000
  is reached from another device; it has to be allowed for the hotspot's
  network (Windows treats it as private).
- **The ESP32 is not on the hotspot.** It talks to the notebook over USB
  only, so its Wi-Fi stays off.

### 6.5 Removing it from the notebook afterwards

1. `docker rmi dod2026` (removes the image), delete the project folder
2. uninstall Docker Desktop in Settings → Apps, if the teacher doesn't want
   to keep it
3. `wsl --unregister docker-desktop` if anything of it is left over
4. remove the firewall rule for port 8000 / Docker, if one was added

## 7. Development (WSL)

Same rule as the other school projects: nothing gets installed in WSL, all
tools run in the Docker image, behind one wrapper script, `./dod`.

### 7.1 Commands

```sh
./dod build            # (re)build the image
./dod test             # each suite on its own: src/hcl, src/backend (pytest), src/frontend (tsc + Vitest)
./dod test backend -x  # one suite; a path picks its suite too: ./dod test src/backend/tests/test_imports.py
./dod backend          # the backend alone on http://localhost:8000, reloads on every save, DOD_INTERNAL_KEY=dev
./dod sim              # backend + Vite dev server on http://localhost:5173, the HCL simulates the board (7.3)
./dod dev              # the same with the board on /dev/ttyUSB0
./dod npm install      # any npm command, run in the node container in src/frontend/
./dod frontend-build   # build the frontend into src/frontend/dist/, which the backend serves on 8000
./dod schema           # the WebSocket messages' JSON Schema, and the frontend's TypeScript types from it
./dod songs [id …]     # download the songs from songs.txt that are not in cache/ yet
./dod backend-soak     # the soak test: 30 min of a simulated open day against the simulated board
./dod shell            # a shell in the container
./dod hcl monitor      # HCL tools: monitor, pattern, bench, repl – see hcl.md section 9
```

Coming with their plans:

```sh
./dod esp upload       # put src/hcl/esp/ on the board, see section 8 (HCL stage 2)
./dod esp run          # run src/hcl/esp/ from the PC without saving it on the board (HCL stage 2)
./dod esp repl         # Python prompt on the board (HCL stage 2)
```

Docker runs outside Claude Code's sandbox: from a sandboxed shell `./dod`
fails with "permission denied" on `/var/run/docker.sock`.

`./dod dev` starts two containers on a private Docker network, both with the
source mounted and both reloading on every save:

- **backend**: uvicorn with `--reload`, `--device /dev/ttyUSB0` and
  `DOD_SERIAL=/dev/ttyUSB0`, port 8000. The board is attached to WSL with
  `usbipd attach --wsl --busid <id>` as in `~/spseke/esp/setup`.
- **frontend**: `node:22-slim` (pinned: `node:22.23.4-slim`) running `vite --host`, port 5173. Vite
  forwards `/api`, `/ws` and `/media` to the backend, so the browser only
  ever talks to 5173, and React changes show up without a page reload.

Both run as the calling user, so `src/frontend/node_modules` and other files they
write are not owned by root. Ctrl-C stops both. The page is reachable from
Windows at `http://localhost:5173`, and from a phone on the same network at
the PC's address (to test the phone screen on a real phone).

### 7.2 Dockerfile

One Dockerfile, two stages:

1. `node:22-slim`: `npm ci` and `npm run build` in `src/frontend/` → `dist/`
2. `python:3.13-slim`: the backend's packages, the `hcl` package
   (`pip install src/hcl`), ffmpeg, yt-dlp with deno, `mpremote` and `esptool`, the
   backend code, and the frontend's `dist/` from stage 1

The final image is what runs on the notebook. In development the same image
runs the backend (with the source mounted over the copied code), so the
backend's environment is identical in both places. Only the frontend's dev
server uses the plain `node` image.

### 7.3 Simulator

With `DOD_SERIAL=sim` (the default), the HCL talks to a simulated ESP32 in
memory instead of a port. It answers like the real one (HELLO, ACKs, even a
fake boot banner) and runs the board's real protocol code; details in
[hcl.md](hcl.md), section 6. The page's previews show the backend's own
frames, so they look the same with or without a board.

This means effects, presets, the logs and the whole frontend can be built
without the hardware at hand. On the day, if the board dies, the main screen
still shows the show.

### 7.4 Tests

- protocol: encode → decode round trip, checksum failure, resync after garbage
- every preset with every parameter extreme renders a frame of the right shape
- the power and flash limits hold for every preset
- the log generator: every template fills in without errors, the rate stays
  within its limits, and real events show up in the stream
- `/internal` roles are refused without the key
- an end-to-end run against the simulator

Before the event: a 2-hour soak test on the real hardware and the notebook.

## 8. ESP32 side and the serial protocol

Everything between the backend's finished frames and the LEDs is the HCL, and
its design is in [hcl.md](hcl.md):

- the backend's interface to it, `submit(frame)` and status/events (sections 3, 10)
- the serial protocol, one FRAME per picture with an ACK (section 5)
- the simulated board used in development (section 6)
- what runs on the ESP32: MicroPython, `src/hcl/esp/` (section 7)
- the Windows serial ↔ TCP bridge (section 8)
- the tools and how the code gets onto the board, `./dod esp upload` (section 9)

MicroPython only has to be flashed once (see `~/spseke/esp/setup/README.md`,
"Flashing MicroPython"). After that, the board's code stays on its flash; the
notebook never changes it.

## 9. Plan

| Phase | Done when |
|---|---|
| 1. HCL | public API, protocol, link, simulated board, tools, tests – no hardware needed ([hcl.md](hcl.md), section 12, step 1) |
| 2. Backend + frontend | built against the simulated board: manual mode (presets, parameters, fades, 8x8), the queue, music mode (downloads, cache, playback, spectrum → light show), the logging page, previews |
| 3. Board | parts wired; `src/hcl/esp/` on the board; `./dod hcl pattern` and `bench` pass in WSL (hcl.md step 2) |
| 4. Notebook | Docker Desktop on the teacher's notebook, the serial bridge, `bench` through it (hcl.md step 3, tech-spec 6.2) |
| 5. Show | fake loading screens, visual polish, idle mode |
| 6. Rehearsal | the whole thing on the notebook, on the stand's network, 2-hour soak test, cache full, `docker save` backup made |

Phases 3 and 4 don't depend on phase 2 – the HCL keeps hardware and app apart.
Phase 4 is the riskiest part of the project, so it happens as soon as the
notebook and the parts are available, in parallel with phase 2, not after it.

## Open questions

Answered:

- strip: 10 LEDs, unmarked (assumed WS2812B, checked in phase 3)
- no LCD: the logs are a web page on the notebook's screen (4.5)
- 8x8: MAX7219 module with DIN/CS/CLK pins, single colour
- music: a fixed, pre-downloaded song list
- control: visitors' phones via a QR code, with the queue in 4.6
- time: enough for all phases
- notebook: the teacher's personal one (6.1, 6.5)
- frontend: React (5.1)
- network: the notebook's Windows Mobile Hotspot (6.4)
- power: a separate 5 V supply (section 2)
- screen: the notebook's screen split – fake terminal left, video right (5.1);
  phones are remotes only

- 8x8 in manual mode: an animated icon per preset, the visitor's drawing
  over it (5.3)

Still open: nothing.
