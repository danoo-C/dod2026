# Plan: HCL

How the hardware communication layer gets built. The design is in
[../hcl.md](../hcl.md); this plan only says in which order, what each step
produces, and how we know it is done. Section numbers like "hcl.md 4.3" point
into the design.

## Goal

The backend can be built on top of `hcl` with `DOD_SERIAL=sim`, and later
switch to the real board by changing only that variable.

## Scope

| Stage | Needs | Contents |
|---|---|---|
| **1. Without hardware** | nothing but WSL + Docker | tooling, protocol, public API, simulated board, link, serial transport, tools, tests |
| 2. Board on the desk | wired board, parts from tech-spec section 2 | MicroPython code, wiring and speed checks |
| 3. Teacher's notebook | Docker Desktop installed on it | Windows serial bridge, speed check through it |

Stage 1 is planned in detail. Stages 2 and 3 are shorter, because what they
need to do depends on what the hardware shows.

Not part of this plan: the backend, the frontend, the Windows launcher
(`start.bat`). The backend's import rule (hcl.md 10) is tested in the
backend's plan.

---

## Stage 1 – without hardware

### Step 1. Tooling

Nothing can run before this: every tool runs in Docker
([school-tools rule](../tech-spec.md#7-development-wsl)).

Files:

- `Dockerfile` – for now only the Python stage: `python:3.13-slim`, the `hcl`
  package installed in editable mode, `pytest`, `mpremote`, `esptool`. The
  Node stage and the backend come later with their own plans.
- `dod` – the dev wrapper, in the style of `~/spseke/esp/setup/esp`: builds
  the image if it is missing, runs as the calling user, mounts the project,
  passes `/dev/ttyUSB0` through if it exists. Only these commands for now:
  `build`, `test`, `shell`, `hcl <tool>`.
- `src/hcl/pyproject.toml` – package `hcl`, Python ≥ 3.13, depends on `pyserial`;
  pytest settings (test paths, a 10 s timeout per test).
- `.gitignore` – `__pycache__/`, `.pytest_cache/`, `cache/`.

Done when:

- [x] `./dod build` builds the image
- [x] `./dod test` runs pytest and reports "no tests" without errors
- [x] `./dod shell` opens a shell as the calling user, files created in it are
  not owned by root

Notes from building it:

- `src/hcl/hcl/__init__.py` exists from this step on (only a docstring): the
  editable install points at the mounted source, so without the package
  folder in the project, `import hcl` fails in the container.
- `.dockerignore` lets only `src/hcl/pyproject.toml` into the build, so the
  image only needs a rebuild when dependencies change.
- `mpremote` and `esptool` are not pinned, like in `~/spseke/esp/setup`
  (built with mpremote 1.29.0, matching the board's MicroPython 1.29).
- Imports are absolute everywhere (`from hcl.transport.base import ...`,
  never `from .base import ...`); `tests/test_imports.py` fails on a relative
  one. This works because `hcl` is installed in editable mode in the image.
  No venv: the container is the environment.

### Step 2. Protocol (hcl.md 5)

Files: `src/hcl/hcl/protocol.py`, `src/hcl/tests/test_protocol.py`

- constants: magic, message types, `PROTOCOL_VERSION = 1`, max payload 512
- `encode(type, payload) -> bytes` with the checksum over header and payload
- `Parser` with `feed(data) -> list of (type, payload)`, resyncing on any
  mismatch, and a way to collect the bytes that were not part of a frame
  (for `garbage_bytes` and `RawText`)
- helpers to build and read each payload (FRAME, HELLO, ACK, LOG)
- written in the MicroPython subset (hcl.md 5.5): no dataclasses, no `typing`,
  no `enum`, `struct` only

Done when:

- [x] round trip for every message type
- [x] wrong checksum, oversized length, garbage before / between / inside
  frames, a frame fed one byte at a time – all parsed correctly
- [x] text between frames comes out as lines
- [x] a test fails if `protocol.py` imports anything outside `struct`
  (a cheap guard for MicroPython compatibility; the real check is in stage 2)

Notes from building it:

- Turning garbage into text lines is in its own file, `hcl/rawtext.py`
  (tests in `test_rawtext.py`), not in `protocol.py`: only the host needs it,
  so it stays off the board.
- After a failed attempt (bad length or checksum) the parser drops only the
  first byte and searches again from the next one. So a real message that a
  broken one ran into is still found (`test_message_hidden_in_a_truncated_one_is_found`).
- The guard test also rejects f-strings, annotations and decorators in
  `protocol.py`, not only imports.
- Checked by breaking the code on purpose: a checksum over the payload only
  (the old tech-spec version) and dropping a whole failed attempt both make
  tests fail.
- To confirm on the board in stage 2: `bytes.find`, `struct` with `s`, and
  negative slices, which `protocol.py` relies on.

### Step 3. Public types (hcl.md 3.2–3.5)

Files: `src/hcl/hcl/types.py`, `src/hcl/hcl/__init__.py`, `src/hcl/tests/test_types.py`

- `Frame` with its shape checks, `DeviceInfo`, `LinkState`, `LinkStatus`
- the events: `Connected`, `Disconnected`, `DeviceLog`, `RawText`, `Incompatible`
- `__init__.py` exports only the public API (`__all__`); `open_link` is added
  in step 6

Done when:

- [x] `Frame` accepts a valid frame and rejects each kind of wrong shape with
  a clear `ValueError`
- [x] `from hcl import Frame, LinkState, LinkStatus` works, internals are not
  in `__all__`

Notes from building it:

- `DeviceInfo` got a `simulated` flag. The design said the simulated board
  reports firmware `0.0.0-sim`, but HELLO's firmware field is three numbers;
  the link sets the flag instead (hcl.md 6 updated).
- `Frame` keeps its own copy of the bytes, so a backend that reuses one
  buffer for every frame can't change a frame after submitting it. It also
  rejects more LEDs than fit into one message (`MAX_LEDS`, 167).
- `LinkStatus.to_dict()` gives JSON-ready data for `/api/status`;
  `LinkState` values are plain strings (`"connected"`).
- Every event has `at`, the time it happened, for the logging page.
- An unknown log level from the board counts as an error (`LogLevel.from_wire`),
  so it is not overlooked.

### Step 4. Simulated board (hcl.md 6)

Files: `src/hcl/hcl/transport/base.py`, `src/hcl/hcl/transport/sim.py`,
`src/hcl/tests/test_sim.py`

- the `Transport` interface (hcl.md 4.1): `open`, `read(max, timeout)`,
  `write`, `close`
- `SimTransport` with a fake board inside that uses `protocol.py`: boot banner
  as plain text, HELLO on PING, ACK after `latency_ms`, keeps the last picture,
  goes "idle" after 3 s without frames
- faults from the URL: `latency_ms`, `drop`, `garbage`, `reboot_every`,
  `unplug_every` (an unplug makes `read`/`write` raise, like a real port)
- a seed option for the random faults, so failing tests can be repeated

Done when:

- [x] PING → boot banner text + HELLO; FRAME → ACK with the same seq; the
  fake board's last picture equals what was sent
- [x] each fault does what it says, with a fixed seed

Notes from building it:

- The board powers on when the port is opened and sends its boot text and
  HELLO by itself, like a real ESP32 reset by opening the port. So the boot
  text comes before the first PING, not after it.
- The boot text is the ESP32's own boot messages (`rst:0x1 (POWERON_RESET)…`);
  MicroPython's banner and `>>>` only appear after a REPL message, as on the
  real board.
- More options than the design listed: `boot_ms`, `unplug_for`,
  `idle_after_ms`, `led_count`, `color_order`, `protocol` (hcl.md 6 updated).
- `hcl/color.py` has the colour-order conversion; the simulated board uses it
  to turn what it received back into RGB, and the link will use it in step 5.
- Stable: 3 runs in a row and one run with every CPU core busy passed,
  97 tests in under 2 s.

### Step 5. The link (hcl.md 4)

Files: `src/hcl/hcl/link.py`, `src/hcl/tests/test_link.py`

The biggest step. In this order, each part tested before the next:

1. the I/O thread and the slot: `start()`, `stop()`, `submit()` from asyncio,
   reading and parsing in the thread
2. the connection states: PING until HELLO, HELLO timeout, INCOMPATIBLE,
   reconnecting with backoff, an unexpected HELLO = reboot
3. sending: one frame in flight, ACK timeout, keepalive, rate cap,
   RGB → the board's colour order
4. status: counters, fps and round-trip time over the last 2 s, `last_error`
5. events: fan-out to several listeners, `call_soon_threadsafe`, a slow
   listener does not block the others or the I/O thread

Tests use the simulated board with shortened timeouts (ACK 20 ms, HELLO
300 ms, keepalive 100 ms), so they stay fast. They wait for conditions with a
deadline instead of fixed sleeps, so they don't fail just because the machine
is busy.

Done when every test from hcl.md 11 passes:

- [x] connects and reports the board from HELLO
- [x] reconnects after an unplug; a reboot gives `Connected(rebooted=True)`
  and the last frame is sent again
- [x] 3 ACK timeouts in a row → DISCONNECTED → reconnects
- [x] another protocol version → INCOMPATIBLE, nothing is sent
- [x] newest frame wins: 100 frames submitted to a slow board, nothing piles
  up, `frames_replaced` counts the skipped ones
- [x] keepalive repeats the last frame, the fake board never goes idle
- [x] colour order: RGB in, GRB on the wire
- [x] `stop()` returns within 1 s and leaves no thread running
- [x] the whole HCL test suite runs in under 30 s (122 tests, ~6 s)

Notes from building it:

- The link is `hcl.link.Link`, built from a transport, a URL (for the status)
  and `LinkOptions` (all timings, defaults for the real board). `open_link`
  in step 6 puts these together from a URL.
- A listener's queue size is set per listener, `events(queue_size=…)`, not
  only once for all: a burst of events bigger than the queue would otherwise
  overflow the fast listeners too (hcl.md 3.5 updated).
- `Disconnected` only comes after `Connected` or `Incompatible`. A board that
  never answers after the port opens doesn't produce events, only
  `last_error` and `reconnects` (hcl.md 3.4 and 3.5 updated).
- A frame submitted before the board answered can have the wrong LED count;
  it is dropped when it would be sent, with `last_error` saying why.
- Async tests run with `asyncio.run` inside plain test functions, so no
  extra pytest plugin is needed. `conftest.py` fails any test that leaves an
  I/O thread running.
- Checked by breaking the code on purpose: no resend after a reboot, not
  waiting for the ACK, no keepalive, keeping the oldest frame instead of the
  newest, accepting late ACKs, no colour reorder – each makes a test fail.
  The first two first slipped through (keepalive or a poorly chosen break
  hid them); the tests were made stricter until they didn't.
- Stable: 3 runs in a row and 3 runs with every CPU core busy all passed.

### Step 6. `open_link` and the serial transport (hcl.md 3.1)

Files: `src/hcl/hcl/transport/serial.py`, `open_link` in `src/hcl/hcl/__init__.py`,
`src/hcl/tests/test_serial.py`

- `open_link(url, **options)`: `sim[?…]` → `SimTransport`, anything else →
  `SerialTransport`; unknown options raise
- `SerialTransport`: `serial_for_url(..., do_not_open=True)`, DTR and RTS off,
  then `open()`; works for `/dev/tty…` and `socket://…`

This can be tested without a board: the test opens a pseudo-terminal pair
(`os.openpty()`), runs the fake board from step 4 on one end and the link with
`SerialTransport` on the other. That runs the real serial code path, only the
cable is missing.

Done when:

- [x] the link connects through the pseudo-terminal and frames are ACKed
- [x] closing the board's end shows up as DISCONNECTED, reopening reconnects
- [x] `socket://` works against a small TCP server in the test that forwards
  to the fake board (this is what the Windows bridge will look like)

Notes from building it:

- `open_link` is in `hcl/connect.py`; `hcl` now also exports `Link`,
  `LinkOptions` and `EventStream`, for type hints in the backend.
- The pseudo-terminal sits behind a symlink, so a test can "unplug" it and
  put a new one behind the same name, like replugging a USB adapter. It is
  switched to raw mode first, or the terminal would echo and change bytes.
- The fake bridge keeps the board's port open when its client goes away, like
  the real one will (hcl.md 8): after a reconnect the board did not reboot, so
  the link gets its HELLO by PINGing. The test checks exactly that.
- The serial transport only reconfigures the port's read timeout when it
  changes; pyserial reconfigures the whole port each time it is set.
- pyserial already flushes the input when it opens a real port; the
  transport's own flush only matters for `socket://`. Kept, with a comment;
  breaking it on purpose shows nothing on a pseudo-terminal for that reason.
- Checked by breaking the code on purpose: DTR left on, and port errors not
  turned into `TransportError`, both make tests fail (the second only after
  the disconnect tests started checking the reason).
- Stable: 138 tests in ~7 s, 3 runs in a row and 3 with every CPU core busy.

### Step 7. Tools (hcl.md 9)

Files: `src/hcl/hcl/tools/monitor.py`, `pattern.py`, `bench.py`, `repl.py`;
`./dod hcl <tool>` in the wrapper

- `monitor` – status line every second plus every event, until Ctrl-C
- `pattern` – each LED red, green, blue in turn, 8x8 row and column sweep,
  brightness ramp; prints what should be visible at each moment
- `bench` – frames as fast as ACKs allow for 20 s (`--seconds`), then fps,
  round-trip min / avg / max, timeouts
- `repl` – sends the REPL frame and exits

Done when:

- [x] all four run against `sim` (`DOD_SERIAL=sim ./dod hcl monitor` shows
  CONNECTED and a frame rate)
- [x] `bench` against `sim` reports a plausible frame rate for the configured
  latency
- [x] Ctrl-C ends each tool cleanly

Notes from building it:

- `monitor` only watches by default, so running it doesn't change what the
  board shows; `--send` adds a test frame. Through `./dod` against `sim` it
  showed 29 fps at 4.2 ms round trip; `bench` showed 239 fps, PASS.
- `bench` needed the fastest and slowest round trip, so `LinkStatus` got
  `rtt_min_ms` and `rtt_max_ms` (hcl.md 3.4 updated).
- `repl` talks to the port without the link (the link would keep PINGing),
  through the new `hcl.connect.open_transport()`. It waits for `main.py` to
  answer before sending REPL, because opening the port can reset the board.
- Found a bug in the simulated board while testing `repl`: it answered PING
  before it had finished booting, so its boot text came after the REPL
  prompt. It now ignores input during `boot_ms`, like a real board (hcl.md 6
  updated, `test_ignores_input_while_booting`).
- The async test helper now keeps the test's signature (`functools.wraps`),
  so async tests can use pytest fixtures like `monkeypatch`.
- Each tool's logic is tested against the simulated board in-process; each
  command line once as a real process, including Ctrl-C (exit code 130, no
  traceback) and a bad URL (exit code 2).
- 158 tests in ~23 s; 2 runs with every CPU core busy passed (~26 s).

### Stage 1 done when

- [x] all checkboxes above are ticked, `./dod test` is green
- [x] the backend can do `from hcl import open_link, Frame` and get a
  connected simulated board – this is what the backend's plan starts from
- [x] [../hcl.md](../hcl.md) is updated wherever the build showed the design
  had to change

**Stage 1 is done** (2026-11-03).

---

## Stage 2 – board on the desk

Needs: the parts from tech-spec section 2, wired as shown there; the board
attached to WSL (`usbipd attach --wsl --busid <id>`).

1. **Board code** (hcl.md 7): `src/hcl/esp/boot.py`, `main.py`, `config.py`,
   `max7219.py`; `./dod esp upload` and `./dod esp repl` in the wrapper.
2. **Protocol on MicroPython:** a small self-test (`./dod esp run` a script
   that encodes and parses every message type with the board's copy of
   `protocol.py`). This is the real check of step 2's compatibility guard.
3. **Wiring:** `./dod hcl pattern` – every LED, the colour order (fix
   `COLOR_ORDER` in `config.py` if needed), every 8x8 row and column.
4. **Speed:** `./dod hcl bench` – 30 fps with room to spare, no ACK timeouts
   over 20 s.
5. **The board's behaviour:** unplug and replug (reconnects by itself), press
   EN (reboot is noticed), stop the backend (idle animation after 3 s), the
   BOOT-button escape and `./dod esp upload` work.

Done when the **(verify)** items in hcl.md 4.2, 5.4 and 7.2 are answered and
the answers are written into hcl.md.

Status (2026-11-04):

- [x] 1. board code: `src/hcl/esp/boot.py`, `config.py` (the real wiring:
  strip on 15; 8x8 DIN 21, CLK 18, CS 19, hardware SPI 2 routed there with
  its MISO on the free input-only GPIO39, because its default MISO is 19),
  `max7219.py` (only changed rows are sent; `MATRIX_MIRROR` / `MATRIX_FLIP`
  for how the module is mounted), `main.py`. `./dod esp upload | run <file> |
  repl` in the wrapper: `hcl repl` asks main.py to step aside first (exit 2,
  "didn't answer", is fine when the board is at `>>>` already), then mpremote.
  The board runs **MicroPython v1.13 (2020)** – everything works on it, but
  a newer one would not hurt (~/spseke/esp/setup/README.md, "Flashing").
- [x] 2. protocol on MicroPython: `src/hcl/esp_tests/protocol_selftest.py`
  with `./dod esp run`: every message type, all 256 byte values, resync –
  11 of 11 pass with the board's own `protocol.py`.
- [x] 3. wiring: `./dod hcl pattern` – checked by eye: red, green and blue are
  right with `COLOR_ORDER = "GRB"`; "row 1 from the top" and "column 1 from
  the left" are where they should be, so no `MATRIX_FLIP` / `MATRIX_MIRROR`.
  Also `src/hcl/esp_tests/strip_test.py`: the strip straight from the board,
  no host, for when the strip stays dark.
- [x] 4. speed: `./dod hcl bench` – **66 fps**, round trip 15 ms (14.7–18.1),
  no ACK timeouts, no reconnects over 20 s: PASS. `monitor --send` at the
  show's rate: 29.5 fps, 12.8 ms.
- [ ] 5. the board's behaviour – **needs your hands**: unplug and replug,
  press EN, stop the backend (idle animation after 3 s), hold BOOT after EN
  (stays at `>>>`), `./dod esp upload` afterwards.
- [x] the (verify) items: opening the port **does** reset the board (4.2);
  all 256 byte values pass both ways (5.4); the byte-by-byte reading doesn't
  stall (7.2) – written into hcl.md.
- `./dod hcl <tool>` uses the attached board when `DOD_SERIAL` isn't set (and
  says which: "dod: hcl pattern on /dev/ttyUSB0"); before, it quietly used the
  simulator, and a pattern run showed nothing on the real strip.
  `DOD_SERIAL=sim ./dod hcl …` for the simulator.
- found on the real board, fixed: the PINGs the host sends while waiting
  queued up during the boot, and the board answered each with a HELLO – every
  connect looked like three reboots. The board drops them before its first
  HELLO; the link (`late_hello_ms`) takes a HELLO within 1 s of a PING with no
  boot text before it as that PING's answer. A test with a queueing fake board
  (`test_queued_ping_answers_are_not_reboots`); 166 HCL tests.

## Stage 3 – teacher's notebook

Needs: Docker Desktop on the notebook (tech-spec 6.1), the board.

1. `src/hcl/bridge/serial-bridge.ps1` (hcl.md 8).
2. `./dod hcl bench` in the container on the notebook through
   `socket://host.docker.internal:7777`: same frame rate as in stage 2, no
   timeouts.
3. Restart the container while the bridge runs: the board does not reset, the
   link reconnects.
4. Unplug the board while everything runs: the bridge and the link both
   recover after replugging.

Done when the **(verify)** in hcl.md 8 is answered. If the bridge is too slow
or unreliable, the fallback is usbipd (tech-spec 6.2 B) – for the HCL that is
only a different URL (`/dev/ttyUSB0`), nothing else changes.

This stage is the riskiest part of the whole project, so it happens as soon
as the notebook is available, not after the backend and frontend.

Status (2026-11-05):

- [~] 1. written, **not run on Windows yet**: `src/hcl/bridge/serial-bridge.ps1`,
  and with it the launcher – `start.bat`, `windows/start.ps1` (tech-spec 6.3)
  and the notebook's self-contained image (the Dockerfile's `notebook`
  stage; `./dod build` now builds `--target dev`). `./dod notebook` builds
  and runs that image in WSL with the simulated board.
- [ ] 2.–4. on the notebook. Before that, on this PC: `usbipd detach` the
  board so Windows sees it as COMx, run the bridge in Windows PowerShell,
  and check it with a client from Windows (or `start.bat` if Docker Desktop
  is here).

## Order and dependencies

```
Step 1 → 2 → 3 → 4 → 5 → 6 → 7     (stage 1, one after another)
                                  ↘
                                    backend plan starts
Stage 2 needs stage 1 + parts.  Stage 3 needs stage 2 + the notebook.
```

Steps 2 and 3 don't depend on each other and could be swapped. Everything
from step 4 on builds on the one before.
