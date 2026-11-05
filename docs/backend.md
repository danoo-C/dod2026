# Backend

Design of the backend and of its connection to the HCL. Status: **design,
not built yet**. What the project does is in [dod.md](dod.md), the system
overview in [tech-spec.md](tech-spec.md), the layer below in [hcl.md](hcl.md).
This file is the source of truth for everything between the browsers and
`hcl.open_link()`.

```
 phones ─┐                     ┌──────────────── backend (one process) ─────────────────┐
         │   HTTP + WebSocket  │                                                        │
 main  ──┼────────────────────▶│  api ──commands──▶ state ◀── queue, player             │
 screen  │◀────────────────────│   ▲                  │                                 │
         │  state, preview,    │   │                  ▼                                 │
 logging─┘  logs               │  hub ◀── preview ── engine (30 fps) ──picture──▶ hardware ──submit──▶ HCL ──▶ ESP32
                               │   ▲                  ▲                                │  ▲
                               │   └──── log lines ── logs ◀──── bus ◀── events ───────┘  │
                               │                                                  status, events
                               └────────────────────────────────────────────────────────┘
```

## 1. What the backend does, and what it doesn't

**Does:**

- holds the **one state** of the stand: mode, preset and its parameters, the
  8x8 drawing, what is playing, the queue
- decides **every LED colour and every 8x8 pixel**, 30 times a second, and
  hands the picture to the HCL
- runs the **queue**: who controls the stand, for how long
- serves the **songs**: the list, the downloads, the files the main screen plays
- writes the **fake logs** for the notebook's terminal, mixed with real events
- talks to every browser over **one WebSocket each**: commands in; state,
  preview and logs out

**Doesn't:**

- talk to the serial port or know the protocol – that is the HCL's job; the
  backend only calls `hcl`'s public API, from one file (section 5)
- analyse audio – the main screen's browser does the FFT and sends the bands;
  the backend turns them into light
- remember anything across restarts – everything is in memory, except the
  song files in `cache/`

## 2. Stack

- Python 3.13, FastAPI, uvicorn with **one worker**: there is one board, one
  state and one queue; several workers would each have their own and fight
  over the port.
- Pydantic v2 for the WebSocket messages and the settings (it comes with
  FastAPI anyway).
- `hcl` (`src/hcl`), installed in editable mode in the same image.
- `yt-dlp` + `ffmpeg` + `deno` for downloading songs (tech-spec 5.2). ffmpeg
  comes from apt; deno comes with yt-dlp itself, from PyPI:
  `yt-dlp[default,pin-deno]==<version>` pins deno to the version that yt-dlp
  wants (decided in plan step 8, instead of copying it from deno's image).
- **No numpy.** The strip has 10 LEDs and the matrix 64 pixels; plain Python
  renders a frame in well under a millisecond, and the image stays smaller.
  If an effect ever needs it, it can be added then.
- `pytest`; FastAPI's `TestClient` for HTTP and WebSocket tests.

## 3. Where it lives

The package is called **`dod`** (imports read `from dod.engine.picture import
Picture`; a generic name like `app` would be ambiguous with absolute
imports). It is installed in editable mode in the image, like `hcl`.

```
src/backend/
  pyproject.toml          package "dod"; depends on hcl, fastapi, uvicorn, pydantic, yt-dlp
  dod/
    main.py               the FastAPI app and its lifespan: builds and wires everything (section 4.1)
    settings.py           settings from environment variables (section 11)
    bus.py                in-process events: who did what (section 4.3)
    tasks.py              the supervisor: restarts a crashed background task (section 4.2)
    state.py              the stand's state and its change notifications (section 6)
    hardware.py           the only module that imports hcl (section 5)
    engine/
      loop.py             the 30 fps render loop (section 7)
      picture.py          Picture: what the engine produces
      color.py            colour helpers: hex, HSV, mixing, luminance
      output.py           OutputStage: brightness, flash limit, power limit, preview, gamma (section 7.3)
      matrix.py           8x8 helpers: icons, bars, text
      effects/
        base.py           Effect, Param: the interface every effect has
        rainbow.py, fire.py, police.py, breathe.py, comet.py, strobe.py, solid.py
        music.py          spectrum → light show
        idle.py           when nobody plays
    control/
      queue.py            turns, as pure logic with an injected clock (section 8)
      sessions.py         the session cookie, roles, the internal key
    music/
      songs.txt           the fixed song list (one YouTube link per line, optional short title)
      library.py          the list, the cache, which songs are ready
      download.py         yt-dlp; also `./dod songs`
      audio.py            the latest spectrum from the main screen, delay, staleness
      player.py           what plays, since when, what's next
    logs/
      generator.py        the fake terminal: real events + filler + bursts (section 10)
      templates.py
    api/
      http.py             pages, /media, /api/*
      ws.py               the WebSocket hub: connections, roles, broadcasting
      messages.py         every WebSocket message as a Pydantic model (section 9)
      schema.py           their JSON Schema → src/backend/schema/messages.json (`./dod schema`)
  tests/
```

## 4. How it fits together

### 4.1 Startup and shutdown

`main.py`'s lifespan is the only place that creates things and connects them
– no globals, no import-time side effects. In order:

1. read the settings
2. create the bus, the state, the queue, the song library, the player
3. create the hardware (section 5): `open_link(DOD_SERIAL)`, subscribe to its
   events, `start()` – connecting runs in the background, nothing waits for it
4. create the engine and start the render loop
5. start the background tasks: HCL events → bus, status poller, queue clock,
   log generator (songs are downloaded beforehand with `./dod songs`, not by
   the running backend – plan step 8)
6. print the internal pages' URLs with the key (`…/internal/main?key=…`), so
   they can be opened in development and are in `docker logs` on the notebook
7. serve

Shutdown in reverse: stop accepting WebSockets, cancel the tasks, stop the
render loop, `await link.stop()`. The last frame is **not** blanked on
purpose: the board shows its own idle animation 3 s after the frames stop
(hcl.md 7.2), so the stand never looks dead, even while the backend restarts.

### 4.2 Tasks

All asyncio, all in one event loop:

| Task | Rate | Does |
|---|---|---|
| render loop | 30 / s | engine → picture → hardware, every 3rd tick also → preview (section 7) |
| hcl events | as they come | the HCL's events → bus (section 5.5) |
| status poller | 1 / s | `link.status` → state's hardware part, numbers for the logs |
| queue clock | 4 / s | ends turns, releases inactive controllers (section 8), ends a song the main screen stopped reporting (section 6) |
| log generator | 3–40 lines / s | real events from the bus + filler (section 10) |
| WebSocket handlers | per message | one per connected browser (section 9) |

A task that crashes is logged and restarted after a second; it never takes
the others down. The render loop in particular must never stop.

### 4.3 The bus

A small in-process publish/subscribe: features announce what happened, and
whoever cares listens. So the log generator can turn "preset changed" into
log lines without the preset code knowing that logs exist.

```python
bus.publish(PresetChanged(preset="fire", by="7f3a"))
async for event in bus.subscribe(): ...
```

`publish()` never waits and must be called from the event loop's thread; a
thread would use `loop.call_soon_threadsafe(bus.publish, event)`. A
listener that runs on its own clock (the log generator) takes what is queued
with `take_all()` instead of iterating.

Events are frozen, keyword-only dataclasses with a wall-clock `at`: `PresetChanged`, `ParamChanged`,
`DrawingChanged`, `SongStarted`, `SongEnded`, `TurnStarted`, `TurnEnded`,
`QueueJoined`, `QueueLeft`, `BoardConnected`, `BoardLost`, `BoardLog`,
`BoardText`, `BoardIncompatible`, `LoadingStarted`. Like the HCL's events,
each listener has its own queue; a slow one loses its oldest events and never
blocks anybody.

## 5. The connection to the HCL

### 5.1 One module owns it

`dod/hardware.py` is the **only** file in the `dod` package that imports
`hcl` (a test checks it, like `hcl`'s own import test). Everything else works
with the backend's own types. Tests may import `hcl` and `hcl.testing`
(section 12), but nothing deeper: the HCL's internals can change. So:

- the engine and the effects can be tested without any hardware code
- the HCL's API can change in one place
- the seam is small enough to read in one sitting

```python
class Hardware:
    def __init__(self, link: hcl.Link, bus: Bus, *, fallback_led_count: int, simulated: bool,
                 on_status: Callable[[HardwareStatus], None] | None = None): ...
    async def start(self) -> None          # subscribe to link.events(), then link.start()
    async def stop(self) -> None           # link.stop()
    async def run_events(self) -> None     # task: HCL events → bus (section 5.5)
    async def poll_status(self) -> None    # task: link.status once a second (section 5.6)
    def handle_event(self, event) -> None  # one HCL event: bus, real log, status
    @property
    def led_count(self) -> int             # the board's, or the fallback before it answered
    def show(self, frame: HardwareFrame) -> None  # one finished picture → hcl.Frame → link.submit
    @property
    def status(self) -> HardwareStatus     # the backend's view of link.status
    def link_status(self) -> dict          # link.status.to_dict(), for /api/status

def check_settings(settings) -> list[str]  # sim options, LED count ≤ hcl.MAX_LEDS (section 11)
def open_link(settings) -> hcl.Link        # hcl.open_link(DOD_SERIAL, baud=DOD_BAUD)
```

`main.py` may not import `hcl` either, so the lifespan gets the link from
`hardware.open_link(settings)`. Tests call `create_app(settings, link=…)`
with a link from `hcl.testing.sim_link()` instead (section 12); `main.py`
only passes it on.

### 5.2 What crosses the seam

| What | Direction | How | Rate | Size |
|---|---|---|---|---|
| finished picture | backend → HCL | `link.submit(Frame)` | 30 / s | 10 × 3 + 8 + 1 bytes |
| connection status | HCL → backend | `link.status`, polled | 1 / s | a snapshot |
| events | HCL → backend | `link.events()` | rare: connects, logs, crashes | small |

Nothing else. The backend never waits for the HCL: `submit()` returns at
once, and if the board is slow the HCL drops older frames (hcl.md 3.3).

### 5.3 Picture → Frame

The engine's output (section 7.3) is already final: brightness, flash limit,
power limit and gamma are applied. `show()` only packs it:

- strip: the list of `(r, g, b)` integers → `bytes`, in RGB (the HCL converts
  to the board's colour order)
- matrix: 8 row bytes, bit 7 = leftmost pixel
- matrix brightness: 0–15

`show()` never raises into the render loop. A `ValueError` from `Frame` or
`submit()` (always a bug, or a board with another LED count – for one tick
after it connects) and a `RuntimeError` from a stopped link (during shutdown)
are logged once per distinct message, and the frame is skipped.

### 5.4 LED count

The engine renders for `hardware.led_count`: the connected board's count from
its HELLO, or `DOD_LED_COUNT` (default 10) before any board answered. Every
effect takes the count as an input, so a strip with more LEDs only needs a new
`LED_COUNT` in `src/hcl/esp/config.py`, not new backend code.

### 5.5 Events → bus

One task reads `link.events()` (subscribed before `start()`, so the first
`Connected` isn't missed) and publishes the backend's own events:

| HCL event | Bus event | Ends up |
|---|---|---|
| `Connected(device, rebooted)` | `BoardConnected` | logs (`esp32 INFO handshake …`), status badge |
| `Disconnected(reason)` | `BoardLost` | logs, badge turns red, real log (`docker logs`) |
| `DeviceLog(level, text)` | `BoardLog` | logs (tagged `esp32`), real log if WARN or ERROR |
| `RawText(line)` | `BoardText` | real log only – a traceback from `main.py` |
| `Incompatible(reason, protocol)` | `BoardIncompatible` | badge with the reason, real log |

### 5.6 Status

The status poller reads `link.status` once a second and keeps the part the
pages need in the state (section 6): connection state, simulated or not,
fps, round trip, last error. It is broadcast when the state or the error
changes, not for every new fps value (`on_status`). `/api/status` returns
`{"link": link.status.to_dict(), "render": {fps, effect, led_count, ticks},
"tasks": {running, restarts}}` – the HCL's view, the render loop's, and the
supervisor's, for debugging. The log generator gets the counters (frames sent,
bytes) for its "real numbers".

### 5.7 When the board is missing

The backend works the same with or without a board. What changes:

| Situation | LEDs | Pages | Badge |
|---|---|---|---|
| `DOD_SERIAL=sim` (development) | none (simulated) | everything works, previews too | grey "simulácia" |
| board connected | the show | everything | green |
| board unplugged / port missing | idle animation from the ESP32, or off | everything keeps working, previews too | red, with the reason |
| board has old code | idle animation | everything | red: "nahraj kód do dosky" (`./dod esp upload`) |

The previews come from the engine, not from the HCL, so the main screen still
shows the show when the board is gone (tech-spec 7.3).

### 5.8 Settings passed through

Only `DOD_SERIAL` and `DOD_BAUD` reach `open_link`. The HCL's timings keep
their defaults (hcl.md 3.1), which are made for the real board; tests set
their own.

## 6. State

One `State` object holds everything a page shows. Commands change it through
methods; every change notifies the WebSocket hub, which broadcasts the whole
state (it is small, ~2 kB) at most 20 times a second.

```jsonc
{
  "now": 1793711000.2,                    // server time; pages compute their clock offset from it
  "mode": "manual",                       // "manual" | "music" | "idle"
  "manual": {
    "preset": "fire",
    "params": { "speed": 1.4, "height": 0.7 },
    "matrix": "icon",                     // "icon" | "drawing"
    "drawing": "183c7effff7e3c18"         // 8 rows as hex
  },
  "music": { "song": "dQw4w9WgXcQ", "title": "Never Gonna Give You Up", "started_at": 1793710972.4,
             "length": 213.0, "playing": true,
             "player_connected": true },  // a main screen is connected and can play
  "queue": { "controller": "7f3a",        // short public id (section 9), never the cookie
             "turn_ends_at": 1793711152.4,
             "turn_over": false,          // time is up, the turn goes on because nobody waits
             "waiting": 3, "paused": false },
  "hardware": { "state": "connected", "simulated": false, "fps": 29.9, "error": null }
}
```

What is different per browser (your place in the queue, whether it's your
turn) is not in the shared state; each connection gets its own `you` message
(section 9).

Times in the state (`turn_ends_at`, `started_at`) are the server's wall
clock. Phone clocks are often off by seconds, so every `state` carries the
server's `now`, and the page counts down against its offset from it. Inside,
the queue and the player use a monotonic clock; only the state converts.

**Modes:**

- **idle** – nobody has control and nothing plays for `DOD_IDLE_SECONDS`: a
  calm effect, and the main screen shows big QR codes. Any command ends it.
  The backend starts in idle, with the rainbow ready as the first preset.
- **manual** – a preset is running. Picking a preset stops a song.
- **music** – a song is playing. Picking a song switches to music; when the
  song ends, the mode goes back to the last preset.

Parameters are remembered per preset: switching to fire and back to the
rainbow keeps the rainbow as it was left. A parameter changed while a song
plays is kept for when the song ends; the mode stays music. The idle
countdown starts at the moment the last controller lost control or the last
song ended (or at the last command, from the main screen too).

Listeners (the WebSocket hub, the render loop) are told **once per change**,
and only when something really changed: a command that stops a song and
switches the preset is one notification; picking the preset that already
runs is none. Bus events from a command are published before the listeners
hear of it.

**Songs.** The main screen plays the song, so the backend depends on it:

- `play_song` is refused with `error: no_player` when no `main` is connected;
  the phone greys the songs out while `music.player_connected` is false
- a song ends when the first of these happens:
  1. the main screen sends `player` with `ended: true`
  2. `started_at + length + 10 s` – the length is known from the download
  3. no `player` message for 10 s while it plays – the main screen was closed,
     reloaded, or the browser blocked autoplay
- if the turn ends while a song plays, the song keeps playing, so the stand
  doesn't suddenly go quiet; the next controller stops it by picking a preset
  or another song

## 7. The engine

### 7.1 The render loop

```
every 1/30 s:
    effect  = the current mode's effect
    picture = effect.render(ctx)             # LED count, time, params, audio, drawing
    out     = stage.apply(picture, now)      # section 7.3: out.hardware and out.preview
    hardware.show(out.hardware)
    every 3rd tick: hub.preview(out.preview) # 10 fps to every page
```

It runs on a fixed timestep with a monotonic clock and catches up without
bursts: a late tick is just late, the next one keeps its slot. An exception
in an effect is logged, that tick shows black, and after 10 failures in a row
the mode switches to idle – one broken effect can't stop the show.

### 7.2 Effects

Every preset is an `Effect` with parameters it declares itself:

```python
class Fire(Effect):
    id = "fire"
    name = "Oheň"                                      # shown on the phone
    params = (
        Param.slider("speed", "Rýchlosť", 0.2, 3.0, default=1.0),
        Param.slider("height", "Výška plameňa", 0.1, 1.0, default=0.7),
    )

    def render(self, ctx: Context) -> Picture: ...   # the strip and the 8x8
```

The effect draws the 8x8 too (`Picture.matrix`). In drawing mode the loop
puts the visitor's drawing in its place (section 7.4).

The phone builds its controls from these declarations (sent once in the
`welcome` message), so adding a preset or a parameter needs no frontend
change. Parameter types: `slider` (number with a range), `color`, `choice`
(a few named options), `toggle`. A wrong declaration (a default out of range,
a choice value twice) fails when the module is imported, not on the day.
Values: slider → float, color → `"#rrggbb"`, choice → the option's value,
toggle → bool; `Param.check()` turns what a phone sent into that or raises
`ValueError`, and an out-of-range value is refused, not clamped.

`Context` gives an effect: the LED count, the time since the effect started,
`dt`, its parameter values, the latest audio (music only), the drawing.
Effects are pure: the same context gives the same picture, which makes them
easy to test.

Presets planned: solid colour (with fades), rainbow, fire, police, breathe,
comet, strobe; plus `music` and `idle`, which phones can't pick.

### 7.3 From picture to output

`Picture` is what an effect produces: per LED `(r, g, b)` as floats 0–1, the
8x8 as 8 row bytes, matrix brightness 0–1. `output.apply()` turns it into what
the hardware gets, always in this order:

1. **master brightness** – one setting for the whole stand
2. **flash limit** – see below (tech-spec 4.3; photosensitive epilepsy)
3. **power limit** – see below
4. **preview** – the picture at this point goes to the pages: screens apply
   their own gamma, so this is what the LEDs look like to a person
5. **gamma** – LEDs look much too bright at low values; a 2.2 gamma table
   makes fades look even
6. to integers 0–255; matrix brightness to 0–15

**Flash limit.** Defined so it can be tested exactly:

- the strip's **level** is its average perceived brightness, 0–1 (per LED
  `0.2126 r + 0.7152 g + 0.0722 b`, averaged over the LEDs)
- a **transition** is a change of the level by at least 0.2 from the last
  peak or low point
- a **flash** is a pair of opposite transitions (up and down); at most 3
  flashes, so at most 6 transitions, in any 1 s window
- when a frame would need a transition over the budget, the **previous output
  frame is repeated** until a transition is allowed again. A beat flash at
  120 BPM is 2 flashes a second and passes untouched. A 20 Hz strobe comes out
  as 3 quick flashes, then a pause until the second is over: the limit is a
  safety net, and the strobe preset itself stays under it (plan step 7).
- the 8x8 is limited the same way, separately, with level = lit pixels / 64 ×
  matrix brightness

**Power limit.** The current is estimated from what the LEDs really get, after
gamma: `sum of gamma(channel) × 20 mA` over all channels (gamma output 0–1).
If it is over `DOD_POWER_LIMIT_MA`, the colour values are scaled down
**before** gamma by `s = (limit / current) ^ (1 / 2.2)`, because
`gamma(s · v) = s^2.2 · gamma(v)`. So the limit is exact, and the preview
(step 4) already shows the dimmed picture without any conversion. While the
limit is on, the final integers are rounded down, so they can't add up to
more than the limit either.

**Matrix brightness 0.** The MAX7219's lowest setting still glows, so when
the 8x8's brightness rounds to 0 of 15, its pixels are sent all off.

### 7.4 The 8x8

Single colour, pixels on or off, one brightness (tech-spec 5.3). What it
shows comes from the mode:

- **manual** – the preset's icon (animated where it makes sense), or the
  visitor's drawing
- **music** – 8 spectrum bars from the 32 bands
- **idle** – a slow "waiting" animation

Which icon for which preset is in tech-spec 5.3 (decided in plan step 7);
the icons are in `engine/matrix.py`, the animations in each effect. Like the
strip, every 8x8 animation stays under the flash limit on its own.

### 7.5 The music light show (strip)

`effects/music.py`. The strip is built from layers, each driven by something
found in the song:

| Layer | Driven by | What it does |
|---|---|---|
| base | the spectrum, the loudness | a moving, many-coloured picture: one of three looks (the spectrum with the bass in the middle, a scrolling gradient, two counter-running waves); faster when louder; its colours move on with every kick, further with more bass |
| kick | a kick | a hit in the kick's colour, in the scene's shape: burst from the centre, whole strip, alternating halves, comet from alternate ends, scattered spots |
| snare | a snare / clap | the outer 3 LEDs of one side in the palette's opposite colour, the other side next time |
| hi-hat | a hi-hat | a glint on a random LED |
| calm | no kicks for 2 s, or the bass under half the song's loudest | the base turns into slow, dimmer waves |
| build | a calm part getting louder, or a snare roll | a riser fills the strip from both ends towards the middle, in stripes running inwards, faster and whiter as it grows |
| drop | a kick with the bass back, after 4 s of calm | a full white hit, and the next scene at once |

Every 32 kicks (~8 bars) and at every drop the scene changes: kick shape (5),
base look (3) and palette (7) in different cycles, so the combinations keep
changing. The 8x8 shows 8 bars of the spectrum that jump up at once and fall
at most 0.8 of their height a second.

**Flash limit.** Planned for, not hit. The flash limit counts steps of the
strip's *average* brightness, so the base is scaled to a brightness that
follows only the loudness (~0.35 s): its pattern and colours can change at
any speed. Snares and glints are small (under a step together). Only kicks
and drops change the average by a step, one flash each, and the main screen
sends at most one kick every 0.34 s. In a fast song (kicks closer than
0.44 s) every second kick is a small hit: new colours and shape, no step.
The 8x8's slowly falling bars keep it under the limit too. Tested on
simulated songs at 90–200 BPM with a breakdown, a build and a drop
(`tests/test_music_audio.py`), and checked offline on the spectra of the 10
songs of the stand (computed the way the browser does): no frame held, at
brightness 1.0 or 0.8. The limit itself is unchanged.

**What is found where.** The kick is found on the main screen, on the
untilted bands (`beat.ts`): spectral flux – how many dB the 5 lowest bands
rose since the last frame – above 3 dB and an outlier against the last
1.5 s, at most one every 0.34 s. (The first version compared the level with
1.4 × its average, but the bands are in dB, where a kick is a few percent:
it found 4–38 kicks in a whole song; this one finds most of them.) The rest
is found by `music/audio.py` on the bands as sent: snares and hi-hats are
onsets of the mid (~400 Hz–3 kHz) and top (~5 kHz+) bands, the same way;
`level`, `calm`, `build` and drops from the loudness, the bass and the
kicks. The song's loudest bass starts over after 1 s without spectra (the
next song).

Effects are pure, so all of it is kept by `music/audio.py` on the delayed
timeline and handed over in `Audio`: the ages of the last few kicks, snares,
hi-hats and the last drop, their counts, `level`, `calm`, `build`, `held`
(the 8x8's falling bars), and the sums the colours move with: `travel`
(loudness over time), `bass` (smoothed over ~1.5 s), `bass_travel` and
`kick_sum` (the bass at each kick, summed). The main screen shapes the bands
for the lights before sending them (`spectrum.ts`, `LightLevels`): +4.5 dB
per octave above 1 kHz so the treble shows as much as the bass, and only the
top 30 dB below the recent peak lit, so quiet parts go dark.

### 7.6 Each song's light show, worked out ahead

`music/timeline.py`. `./dod songs` makes `<id>.show.png` for every
downloaded song: the strip over the whole song, one column per frame (30 a
second), 4 px per LED with 1 px between (49 px high, so its rows stay sharp
at that height). The main screen shows it under the video, stretched over
the width, with a playhead at the video's position and the part already
played dimmed (`Player.tsx`, `ShowTimeline`); a song without one shows none.

It is made the way the live show is: the song's sound from ffmpeg, the
spectrum as the browser makes it (Web Audio's analyser: Blackman window,
2048-point FFT, smoothing 0.5, the byte range; then `spectrum.ts` and
`beat.ts`, copied – `tests/test_timeline.py` checks the constants against
the frontend's files), then the backend's own `AudioInput`, music effect and
output stage at full brightness. The live show differs only by the
network's timing. numpy does the FFT; the engine itself still doesn't use it.

`<id>.show.json` (written last) holds `VERSION`, a hash of the code that
makes the show (music.py, base.py, output.py, color.py, audio.py,
timeline.py; `\r\n` counted as `\n`, so a Windows checkout hashes the
same). A picture from another version is stale: `/media/<id>.show.png`
answers 404 for it, the backend logs at start how many songs lack a current
one, and the next `./dod songs` makes them again (no internet needed).

## 8. The queue

`control/queue.py` is pure logic: no I/O, no asyncio, the clock is passed in.
So every rule in tech-spec 4.6 can be tested in microseconds with a fake
clock.

```python
q.join(session, now); q.leave(session, now)
q.activity(session, now)            # any command from the controller
q.connected(session, now) / q.disconnected(session, now)
q.song_started(session, now)        # their song counts as activity while it plays
q.song_ended(now)                   # it ended by itself: their turn is over
q.song_stopped(now)                 # someone picked something else: no turn is over
q.skip(now); q.pause(now); q.resume(now)   # admin
q.tick(now)                         # 4 times a second (the queue clock), and after every change
```

Every call that changes something returns the bus events it caused
(`QueueJoined`, `QueueLeft(reason)`, `TurnStarted`, `TurnEnded(reason)`);
the state publishes them. Sessions are public ids, never cookies. The
WebSocket layer calls `connected()` on a session's first connection and
`disconnected()` when its last one closes.

Rules, from tech-spec 4.6, made exact:

- one controller at a time; a turn is 3 min (`DOD_TURN_SECONDS`) or until
  the song they started ends
- **the 3 minutes and the song end only end a turn if someone is waiting.**
  When either happens with nobody waiting, the turn is *over* (`turn_over` in
  the state) and goes on; it ends as soon as someone joins.
- **an inactive controller always loses control**, even when nobody waits
  (otherwise someone who walked away would hold the stand forever and idle
  mode would never start). Inactive means either:
  - connected, but no command for 30 s (`DOD_INACTIVE_SECONDS`)
  - disconnected for 30 s – enough for a page reload or a short phone lock

  A song they started counts as activity while it plays – also offline, so
  nobody loses control while watching their own song with the phone locked;
  the 30 s start again when the song ends. Offline time from before their
  turn started doesn't count. When nobody waits, nobody has control
  afterwards, and idle mode follows (section 6).
- `song_ended` only ends the turn of the controller who started that song;
  a song still playing from the previous turn doesn't end the new one
- after a turn: back of the line if they join again, no permanent lock-out
- a page reload keeps the place: the session is in the cookie, not the
  connection
- **a waiting visitor offline for 30 s leaves the queue** (`QueueLeft`,
  reason `gone`), so the line doesn't wait 30 s for every phone that left the
  Wi-Fi when its turn comes
- **paused** (admin): turns don't end by time or song, and no new turn
  starts; inactivity, leaving and skip still end one. Resuming adds the
  paused time to the current turn.

**Permissions** (checked in `api/ws.py`, before a command reaches the state):

| Command | Who may send it |
|---|---|
| join / leave the queue | any phone |
| preset, parameter, drawing, song | the current controller; the main screen |
| spectrum, player progress | the main screen only |
| skip, pause the queue, stop the song | the main screen only (admin) |

A command from a phone that isn't in control gets `error: not_your_turn` and
changes nothing.

## 9. WebSocket messages

One WebSocket per browser: `/ws?role=phone|main|logging`. Every message is
JSON with a `type`, validated by a Pydantic model in `api/messages.py`; an
unknown or malformed one gets an `error` reply and is otherwise ignored. An
incoming message over 64 kB closes the connection (uvicorn
`--ws-max-size 65536`; the largest real message, `spectrum`, is ~1 kB).

**Sessions.** The page calls `GET /api/session` before it opens the
WebSocket. It sets the cookie `dod_session` if it is missing (random, 128
bits, `HttpOnly`, `SameSite=Lax`) and returns the short id shown in the logs
(`{"session": "7f3a"}`). `GET /` sets it too.

The token in the cookie is a secret: whoever has it holds that place in the
queue. It never leaves `control/sessions.py`. The queue, the state and the
logs use the **public id**, the first 12 hex characters of its SHA-256, and
screens show the first 4 (`7f3a`) – the fake terminal is on a public screen,
and a photo of it must not give a place in the queue away. Because it goes through `/api`,
it works the same behind Vite's dev server, which serves `/` itself. The
WebSocket handshake carries the cookie; a WebSocket without it is closed with
code `4401`, and the page calls `/api/session` and connects again.

**Roles.** `main` and `logging` need the internal key: the launch script opens
the pages with `?key=…`, the page passes it on to `GET /api/session?key=…`,
and the server checks it (constant time) and sets the cookie `dod_internal`
– `HttpOnly`, so no page script holds the key afterwards, and through
`/api` it works behind Vite too. A wrong key gets 403. The WebSocket
handshake carries the cookie, and the server compares it again. Without it the connection is closed with code
`4403` (tech-spec 5.1). In development `./dod backend` sets
`DOD_INTERNAL_KEY=dev`, and the backend prints the internal URLs at startup
(section 4.1).

Only one `main` connection is the music source. A newer one (a reload, or a
second window) replaces the older, which is closed with code `4001`
(`replaced`). The page doesn't reconnect after `4001`: it shows "Otvorené v
inom okne" and a button to take over, so two windows can't keep replacing
each other.

| Close code | Meaning | The page |
|---|---|---|
| `4400` | no or unknown `role` in the URL | a bug: shows an error |
| `4401` | no session cookie | calls `/api/session`, reconnects |
| `4403` | `main` / `logging` without the right key | shows an error, doesn't reconnect |
| `4001` | replaced by a newer `main` | shows "Otvorené v inom okne", reconnects only on the button |
| `1009` | a message over 64 kB | a bug: reconnects with backoff |
| `1001` | the backend shuts down | reconnects with backoff |
| other | network, server restart | reconnects with backoff |

The server accepts the WebSocket before it checks anything, so a refused
page sees the close code instead of a failed handshake. Every connection has
its own outgoing queue (64 messages) and writer task: a slow phone never
holds up the others, and when its queue is full its oldest message is
dropped (`state` and `you` are full snapshots, so the newest is enough).

**Browser → server**

| `type` | From | Fields |
|---|---|---|
| `join_queue`, `leave_queue` | phone | – |
| `set_preset` | controller, main | `preset` |
| `set_param` | controller, main | `name`, `value` |
| `set_matrix` | controller, main | `mode` (`icon` / `drawing`), `drawing` (16 hex chars) |
| `play_song` | controller, main | `song` |
| `loading_started` | any | – (starts a burst in the logs) |
| `spectrum` | main | `bands` (32 floats 0–1), `beat` (bool) |
| `player` | main | `song`, `position` (s), `ended` (bool) |
| `admin` | main | `action`: `skip`, `pause_queue`, `resume_queue`, `stop_song` |

**Server → browser**

| `type` | To | When | Fields |
|---|---|---|---|
| `welcome` | each, once | on connect | role, own short session id, presets with their parameters, songs, public URL, turn length, inactivity limit, the hotspot's name and password for its QR code (`main` only, `null` for the others or without `DOD_WIFI_*`) |
| `state` | all | on change, ≤ 20 / s | the state from section 6, with the server's `now`; changes in between are coalesced |
| `you` | each | when it changes for that browser | short session id, position in the queue (0 = in control), in control or not, turn end |
| `preview` | all | 10 / s | strip as `"#rrggbb"` strings, the 8x8 as 16 hex characters (like the drawing), brightness 0–15 |
| `log` | main, logging | as written | lines (section 10) |
| `error` | the sender | on a rejected command | `code`, `message` |

Error codes: `invalid` (unknown or malformed message, or a value the state
refuses), `forbidden` (a message this role may never send, like `admin` from
a phone), `not_your_turn`, `no_player` (a song, but no main screen to play
it), `unknown_song`, `rate_limited` (sent once when a phone starts being
dropped). Unknown fields are refused too, so a typo doesn't pass silently.

A phone sends at most ~20 commands a second (a slider being dragged); more is
dropped. The main screen's `spectrum` is exempt (30 / s).

**HTTP routes:**

| Route | Does |
|---|---|
| `GET /`, `/internal/main`, `/internal/logging` | the frontend's `index.html` (a placeholder until the frontend exists); `/` also sets the session cookie |
| `GET /api/session[?key=…]` | sets the session cookie if missing, returns `{"session": "7f3a", "internal": bool}`; with the right key also sets `dod_internal`, with a wrong one 403 |
| `GET /api/status` | the link, the render loop, the tasks, the number of connections (section 5.6) |
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/songs` | the song list and which songs are downloaded |
| `GET /media/<id>.mp4` | a downloaded song, with range requests (seeking). `<id>` must match `^[A-Za-z0-9_-]{11}$` **and** be on the song list, otherwise 404 – it is never used to build a path before that check |
| `GET /media/<id>.show.png` | its light show over the whole song (7.6), the same checks; 404 also when it has none or a stale one |

**Types in the frontend.** The frontend gets its TypeScript types from the
same Pydantic models: `./dod schema` writes their JSON Schema to
`src/backend/schema/messages.json` (a test fails when it is out of date), and
the frontend build turns it into `.ts` (in the Node container). Incoming
messages are described as the server accepts them, outgoing ones as it sends
them – every field present, `type` always required, so TypeScript can tell
the messages apart by it. A renamed field then breaks the frontend's type
check instead of the stand.

## 10. The fake logs

Design of the content is in tech-spec 4.5. Inside the backend:

- the generator listens to the bus and turns real events into lines (`queue
  INFO session 7f3a… acquired control (2 waiting)`), and fills the gaps with
  templates (`photon-bus WARN coherence drift 0.03%`)
- real numbers come from the hardware status (bytes, fps, round trip) and the
  engine (the render loop's frame counter, the last frame for hex dumps,
  current preset, beat – the beat from step 8 on)
- calm: 3–8 filler lines every second, spread out over it
- a parameter or the drawing gives at most one line per 0.5 s, with the
  latest value: a dragged slider sends 20 changes a second
- `LoadingStarted` and `SongStarted` start a burst (30–50 lines in 1–2 s),
  and the filler pauses meanwhile; at most one burst every 3 s for the whole
  stand, so a phone can't keep the terminal bursting by sending
  `loading_started` over and over. A trigger in between is dropped, not saved
- the last 300 lines are kept, so a logging page that connects (or reloads)
  starts with a full screen: the hub sends them right after `you`, before any
  new line
- lines are sent in batches (`{"type": "log", "lines": [...]}`), at most ~20
  batches a second, only to `main` and `logging`
- a line is structured, the page does the colours:
  `{"t": 1793710972.481, "tag": "rgb-core", "level": "INFO", "text": "frame 008412 committed"}`.
  The levels are the page's four colours: `DEBUG`, `INFO`, `OK`, `WARN`. A
  board's own `ERROR` shows as `WARN` (it is in the real log too); its text is
  cut to one line of at most 120 characters

Real errors never go to the fake terminal (tech-spec 4.5): they go to the
Python log (`docker logs`) and to the status badge.

## 11. Settings

All from environment variables, read once at startup (`settings.py`):

| Variable | Default | |
|---|---|---|
| `DOD_SERIAL` | `sim` | the board, see hcl.md 3.1 |
| `DOD_BAUD` | 115200 | |
| `DOD_LED_COUNT` | 10 | used until the board says how many it has |
| `DOD_POWER_LIMIT_MA` | 1500 | for the strip; the 5 V / 3 A supply also feeds the 8x8 |
| `DOD_BRIGHTNESS` | 0.8 | master brightness, 0–1 |
| `DOD_TURN_SECONDS` | 180 | |
| `DOD_INACTIVE_SECONDS` | 30 | |
| `DOD_IDLE_SECONDS` | 30 | nobody plays for this long → idle mode |
| `DOD_AUDIO_DELAY_MS` | 0 | delay the light show, for a Bluetooth speaker (tech-spec 5.2) |
| `DOD_INTERNAL_KEY` | random at start | the launch script sets it (tech-spec 6.3); `./dod backend` sets `dev`; printed at startup either way |
| `DOD_PUBLIC_URL` | `http://localhost:8000` | for the QR code |
| `DOD_CACHE_DIR` | `/work/cache` | the songs |
| `DOD_LOG_LEVEL` | `INFO` | the real log |
| `DOD_WIFI_SSID` | – | the hotspot's name, for the main screen's Wi-Fi QR code (tech-spec 6.4); with `DOD_WIFI_PASSWORD` or not at all |
| `DOD_WIFI_PASSWORD` | – | its password, 8–63 characters; sent in the main screen's `welcome` only |

Wrong values (a negative brightness, an unknown serial URL) stop the backend
at startup with a clear message, instead of misbehaving later. Every wrong
variable is named at once, and an unknown `DOD_` variable is an error too
(`DOD_BRIGHTNES: unknown setting, did you mean DOD_BRIGHTNESS?`), so a typo
doesn't silently run with the default. `DOD_SERIAL` only gets a check of its
form in `settings.py`; its `sim?…` options and the LED count's upper limit
(`hcl.MAX_LEDS`) are checked when the hardware is created, since only
`hardware.py` may import `hcl` – still at startup.

## 12. Tests

- **effects:** every preset, with every parameter at its minimum, maximum and
  default, renders a picture of the right shape for 1, 10 and 60 LEDs; same
  context → same picture
- **output:** with the definition in section 7.3, at most 6 transitions in
  any 1 s window, also for a 20 Hz strobe; a 2 Hz beat passes untouched; the
  power limit holds exactly for an all-white picture; gamma keeps 0 and 1; the
  preview is the picture before gamma
- **queue:** every rule in section 8 with a fake clock, including: an inactive
  controller loses control with nobody waiting; their own song keeps them
  active; a song from the previous turn doesn't end the new one
- **songs:** each of the three ways a song ends (section 6); `no_player`
- **messages:** every message type parses; unknown and malformed ones give
  `invalid`; the JSON Schema for the frontend is up to date
- **WebSocket:** with `TestClient` – no cookie → `4401`, `/api/session` →
  connects; roles and the internal key (`4403`); a second `main` closes the
  first with `4001`; permissions (`not_your_turn`); a command changes the
  state and everyone gets it
- **HTTP:** `/media` refuses ids that don't match or aren't on the list
- **the HCL seam:** with `hcl.testing.sim_link()` – a real link to the
  simulated board with fast timings, and a handle on the board: a phone picks
  a preset → `board.strip_rgb()` shows it; `board.unplug()` → the badge goes
  red and the previews keep running; inside `dod/` only `hardware.py` imports
  `hcl`, and tests import nothing from `hcl` but `hcl` and `hcl.testing`
- **one end-to-end run:** the whole app with `DOD_SERIAL=sim` for a few
  seconds, a phone and a main screen connected, nothing crashes

The suite stays under 30 s, so timing checks are short: the render loop's
30 fps is checked over 3 s in the suite and over the whole run in the soak
test. The backend sets its own pytest timeout (15 s per test; `hcl`'s is 10).

## Open questions

Decisions this design makes, to confirm or change:

1. The package is called `dod` (section 3).
2. No numpy (section 2).
3. Only `hardware.py` imports `hcl`; the rest of the backend uses its own
   `Picture` (section 5.1).
4. The whole state is broadcast on every change, not just what changed
   (section 6): simpler, and at ~2 kB × 20 / s × 8 phones it is ~320 kB/s
   at worst on the hotspot.
5. The frontend's TypeScript types are generated from the backend's Pydantic
   models (section 9), instead of being written twice by hand.
6. `DOD_POWER_LIMIT_MA` defaults to 1500 for the strip, with the 3 A supply
   (section 11). Full white on 10 LEDs is 600 mA, so this only matters if the
   strip ever gets longer.

Decided in plan step 7: the 8x8 in manual mode (tech-spec 5.3).

Decided in the review on 2026-11-03, already written into the sections above:
inactivity always releases control (8); the three ways a song ends and
`no_player` (6); the session from `/api/session` and the close codes (9); the
dev key and the printed URLs (4.1, 11); `hcl.testing` for the tests (5.1, 12);
the exact flash limit and the output order with the preview before gamma
(7.3); the server's `now` in the state (6); the `/media` id check, the
message size limit and the burst limit (9, 10).
