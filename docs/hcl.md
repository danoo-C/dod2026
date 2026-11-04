# HCL – hardware communication layer

Design of the layer between the backend and the ESP32. Status: **the host
side is built and tested against the simulated board** (stage 1 of
[plans/hcl.md](plans/hcl.md)); the board's code and the Windows bridge are
not built yet. The rest of the system is in [tech-spec.md](tech-spec.md); this
file is the source of truth for everything between the backend's finished
frames and the LEDs, including the serial protocol.

```
frontend ⇄ backend ──submit(frame)──▶ HCL ──serial──▶ ESP32 ──▶ strip, 8x8
                    ◀──status, events──     ◀──HELLO, ACK, LOG──
```

## 1. What the HCL does, and what it doesn't

**Does:**

- takes finished frames from the backend and gets them onto the board
- talks the serial protocol (section 5), on both ends: the host side in Python,
  the device side in MicroPython
- finds out what is connected (HELLO: protocol version, LED count, colour order)
- keeps the connection alive: reconnects after an unplug, notices a board
  reboot, resyncs after garbage on the line
- reports status (connected or not, fps, round-trip time, errors) and events
  (connected, disconnected, log messages from the board)
- includes a simulated board, so everything above it runs without hardware

**Doesn't:**

- decide anything about what is shown – no effects, no presets, no music
- apply the power or flash limit – the backend does that before submitting,
  so the simulated and the real board always get identical frames
- know about the frontend, the queue or the logs page

The backend only ever sees the public API in section 3. Everything behind it
(transports, protocol, threads) can change without the backend noticing.

## 2. Where it lives

The HCL is a Python package, `hcl`, in `src/hcl/`. The backend imports it and
runs it **in the same process** and the same container.

Why not a separate service: it would add a second network hop, a second
container and its own failure modes, and buy nothing – the backend is the only
user. The boundary is kept by the package's public API, not by a network.

```
src/hcl/
  pyproject.toml          package "hcl", depends on pyserial; installed into the backend's image
  hcl/
    __init__.py           public API: open_link, Frame, LinkStatus, LinkState, events
    connect.py            open_link(): picks the transport from the URL
    link.py               Link: connection state machine, sender, stats
    types.py              Frame, DeviceInfo, LinkStatus, the events
    protocol.py           frame encoding and parsing – shared with the board (section 5.5)
    rawtext.py            readable text among the garbage → RawText lines
    testing.py            sim_link(): the simulated board for the backend's tests (section 3.6)
    color.py              RGB ↔ the strip's colour order
    transport/
      base.py             Transport interface
      serial.py           real port via pyserial (also socket:// URLs)
      sim.py              simulated ESP32
    tools/
      monitor.py          watch status and events
      pattern.py          wiring test pattern
      bench.py            throughput test
      repl.py             send the REPL frame (before uploading code)
  esp/                    MicroPython code for the board (section 7)
    boot.py
    main.py
    config.py
    max7219.py
  bridge/
    serial-bridge.ps1     Windows COM port ↔ TCP (section 8)
  tests/
```

## 3. Public API

Everything the backend uses, all from `hcl`:

```python
from hcl import open_link, Frame, LinkState

link = open_link(os.environ.get("DOD_SERIAL", "sim"))
await link.start()

# every render tick (30 fps), never blocks:
link.submit(Frame(strip=rgb_bytes, matrix=rows, brightness=8))

link.status            # LinkStatus snapshot, see below
async for event in link.events():
    ...                # Connected, Disconnected, DeviceLog, RawText, Incompatible

await link.stop()
```

### 3.1 `open_link(url, **options) -> Link`

| `url` | Transport |
|---|---|
| `sim` | simulated board (default) |
| `sim?latency_ms=8&drop=0.02&reboot_every=60` | simulated board with faults, for tests |
| `/dev/ttyUSB0` | real port (development in WSL) |
| `socket://host.docker.internal:7777` | real port through the Windows bridge (notebook) |

Options, all with defaults; the backend passes them from environment variables:

| Option | Default | Meaning |
|---|---|---|
| `baud` | 115200 | serial speed |
| `ack_timeout_ms` | 100 | give up waiting for an ACK |
| `hello_timeout_ms` | 5000 | wait for HELLO after connecting |
| `keepalive_ms` | 1000 | resend the last frame if nothing new came |
| `max_fps` | 60 | never send faster than this |

### 3.2 `Frame`

```python
@dataclass(frozen=True)
class Frame:
    strip: bytes       # LED count × 3, R G B per LED, 0–255, in strip order
    matrix: bytes      # 8 bytes, row 0 = top, bit 7 = leftmost pixel
    brightness: int    # 0–15, the matrix's brightness (the MAX7219 has one for all pixels)
```

The backend always sends RGB. The board's colour order (GRB on most WS2812B)
comes from HELLO, and the HCL reorders the bytes before sending, so the board
can copy them straight into its LED buffer.

`submit()` raises `ValueError` if the frame has the wrong shape (strip length
not a multiple of 3 or not matching the connected board, matrix not 8 bytes,
brightness out of range). That is always a backend bug, so it fails loudly.

### 3.3 `submit()` – the newest frame wins

`submit()` puts the frame into a single slot and returns immediately. If the
slot already holds a frame that wasn't sent yet, the new one replaces it (and
`frames_replaced` goes up). The HCL sends from that slot at the pace the board
can take.

So the render loop never waits for the serial port, a slow link lowers the
frame rate instead of building up a delay, and the lights never lag behind the
music. Before the board is connected, `submit()` still works: the newest
frame waits in the slot and goes out as soon as the board answers.

### 3.4 `LinkStatus`

A snapshot, safe to read at any time:

| Field | |
|---|---|
| `state` | `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `INCOMPATIBLE` |
| `url` | what was opened |
| `device` | from HELLO: protocol version, firmware version, LED count, colour order, and whether it is the simulated board – or `None` |
| `connected_since` | time of the last HELLO |
| `fps` | frames acknowledged per second, last 2 s |
| `rtt_ms` | average send → ACK time, last 2 s |
| `rtt_min_ms`, `rtt_max_ms` | fastest and slowest of those |
| `frames_sent`, `frames_acked`, `frames_replaced` | counters |
| `ack_timeouts`, `garbage_bytes` | counters |
| `reconnects` | how often the link had to start over: the board was lost, or never answered after opening the port |
| `bytes_tx`, `bytes_rx` | counters |
| `last_error` | text of the last problem, or `None` |

The counters are real numbers the fake terminal can show (tech-spec 4.5), and
`state` + `last_error` feed the status badge on the main screen.

### 3.5 Events

`link.events()` gives each caller its own async iterator, so the log generator
and the status badge can both listen. It receives every event from the moment
`events()` is called (so call it before `start()` to also get the first
`Connected`), and ends when the link stops.

Each listener has its own queue, 1000 events by default
(`events(queue_size=…)`). A listener that falls further behind loses its
oldest events (counted in its `dropped`), never holding up the link or the
other listeners.

| Event | When |
|---|---|
| `Connected(device, rebooted)` | HELLO received; `rebooted=True` if the board restarted while connected |
| `Disconnected(reason)` | port lost, or too many ACK timeouts – only after `Connected` or `Incompatible`; a board that never answered shows up in `last_error` instead |
| `DeviceLog(level, text)` | a LOG frame from the board |
| `RawText(line)` | readable text that was not in a frame – MicroPython's boot banner or a crash traceback |
| `Incompatible(reason)` | the board speaks a different protocol version |

`RawText` matters more than it looks: if `main.py` crashes, MicroPython prints
the traceback on the same port, and this is how it shows up in the backend's
log instead of being skipped as garbage.

### 3.6 `hcl.testing` – for the backend's tests

The backend's tests need a link to the simulated board **and** a look at the
board: what it shows, and pulling its cable at an exact moment. The
transports are not part of the API, so this is the one supported way in:

```python
from hcl.testing import sim_link

link, board = sim_link("sim?led_count=12")   # not started; fast timings
await link.start()
link.submit(frame)
board.strip_rgb()      # what the strip shows, back in RGB (None before the first frame)
board.picture          # the last frame as received: strip (board's colour order), matrix, brightness
board.unplug()         # the open port fails now; reopening fails until replug()
board.replug()
await link.stop()
```

- `sim_link(url="sim", **timings) -> (Link, SimBoard)`: `url` is a sim URL
  (section 6); the timings default to `hcl.testing.FAST` (ACK timeout 40 ms,
  HELLO timeout 300 ms, keepalive 100 ms, backoff 20/40 ms), and an unknown
  one raises `ValueError`, like `open_link()`
- `SimBoard`: `led_count`, `strip_rgb()`, `picture`, `frames_received`,
  `boots`, `idle`, `plugged`, `unplug()`, `replug()`
- `unplug()` happens exactly when it is called, unlike `unplug_every`, so a
  test doesn't depend on a timer. The link sees a lost port (`Disconnected`,
  then failed reopens in `last_error`), and reconnects on its next attempt
  after `replug()`.

It is not exported from `hcl` itself; production code never needs it.

## 4. Inside the link

### 4.1 Threads

The port is blocking I/O (pyserial, also for `socket://`), so the link has
**one I/O thread** that owns the transport. It reads with a short timeout
(10 ms), parses, and writes whatever is in the slot. The asyncio side only
touches the slot (under a lock) and receives events via
`loop.call_soon_threadsafe`. The backend's event loop never blocks on the port.

The simulated transport has the same blocking interface, so the I/O thread is
exactly the same code for `sim` and for real ports.

```python
class Transport(Protocol):
    def open(self) -> None: ...
    def read(self, max_bytes: int, timeout: float) -> bytes: ...   # b"" on timeout
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...
```

### 4.2 Connection states

```
            open ok, send PING
DISCONNECTED ─────────────────▶ CONNECTING ──HELLO, same protocol──▶ CONNECTED
     ▲                              │  │                                │
     │      no HELLO in 5 s,        │  └──HELLO, other protocol──▶ INCOMPATIBLE
     └──────port error──────────────┘                                   │
     ▲                                                                  │
     └──port error, or 3 ACK timeouts in a row──────────────────────────┘
```

- **Opening:** DTR and RTS are set off before the port opens
  (`serial_for_url(..., do_not_open=True)`, then `dtr = rts = False`, then
  `open()`), so opening it doesn't reset the board. If it resets anyway
  **(verify)**, the board sends HELLO after booting, which is why the HELLO
  timeout is 5 s and not shorter. Input is flushed, then PING, repeated every
  500 ms until HELLO comes.
- **Reconnecting:** after an error the link waits 0.5, 1, 2, then 5 s between
  attempts, forever. Unplugging and replugging the board needs nothing else.
- **Unexpected HELLO** while connected means the board rebooted:
  `Connected(rebooted=True)`, sequence numbers start over, and the last frame
  is sent again right away.
- **INCOMPATIBLE:** nothing is sent; the link sends PING every 5 s in case the
  board gets new code meanwhile.

### 4.3 Sending

- At most **one frame in flight**. After sending FRAME with sequence number
  `n`, the link waits for `ACK n` (up to `ack_timeout_ms`). Only then the next
  frame goes out. An ACK with another number is ignored (a late one).
- **Keepalive:** if the slot stays empty for `keepalive_ms`, the last frame is
  sent again. The board falls back to its idle animation after 3 s without
  frames (section 7.2), so this keeps a static scene (one fixed colour) from
  turning into the idle animation while the backend is fine.
- **Rate cap:** never more than `max_fps` frames per second, even if ACKs come
  back fast.

With 10 LEDs a frame is 46 bytes on the wire, about 4 ms at 115200 baud.
Writing to the strip takes ~0.3 ms, so the round trip should be well under
10 ms, and 30 fps uses about 1.4 kB/s of the ~11 kB/s the port can do.

## 5. Protocol

### 5.1 Framing

Same in both directions:

```
A5 5A | type (1) | length (2, little endian) | payload (length bytes) | checksum (1)

checksum = (type + length_lo + length_hi + sum(payload)) & 0xFF
```

The checksum includes the header, so a corrupted length is caught too. A
payload longer than 512 bytes is impossible here and treated as garbage.

### 5.2 Types

| Type | Name | Direction | Payload |
|---|---|---|---|
| `0x01` | FRAME | → board | seq (1), strip (LED count × 3, board's colour order), matrix (8), brightness (1) |
| `0x02` | PING | → board | – ; the board answers with HELLO |
| `0x7F` | REPL | → board | – ; the board turns Ctrl-C back on and exits to the REPL |
| `0x81` | HELLO | ← board | protocol version (1), firmware version (3: major, minor, patch), LED count (2, LE), colour order (3 ASCII, e.g. `GRB`) |
| `0x82` | ACK | ← board | seq (1) of the frame that is now on the LEDs |
| `0x83` | LOG | ← board | level (1: 0 info, 1 warn, 2 error), UTF-8 text |

One FRAME carries the whole picture – strip, matrix and brightness – so there
is one ACK per picture and the two can never get out of step.

For 10 LEDs: payload 1 + 30 + 8 + 1 = 40 bytes, 46 bytes with framing.

### 5.3 Parsing

A small state machine, the same on both sides: wait for `A5`, then `5A`, read
type and length, read the payload, check the checksum. On any mismatch it drops
what it has and looks for `A5` again from the next byte. On the host, a frame
that doesn't complete within 50 ms is dropped as well.

Bytes outside frames count as `garbage_bytes`. On the host, if they are
readable text, they are collected into lines and become `RawText` events.

### 5.4 The REPL port

The board's USB serial port is also MicroPython's REPL, which has three
consequences:

- byte `0x03` (Ctrl-C) inside a frame would stop the program, so `main.py`
  calls `micropython.kbd_intr(-1)` once it runs
- `main.py` must never `print()`; everything goes through LOG frames
- **(verify)** that `sys.stdin.buffer` / `sys.stdout.buffer` pass all 256 byte
  values through unchanged (no `\n` → `\r\n`) – the checksum would catch it,
  but every frame would fail

### 5.5 One protocol file for both sides

`hcl/protocol.py` is written in the subset of Python that also runs on
MicroPython: constants, `encode(type, payload) -> bytes`, and a `Parser` class
with `feed(data)` that returns finished frames. No dataclasses, no typing at
runtime, only `struct`.

`./dod esp upload` copies this same file onto the board. So:

- host and board can never disagree about the format
- `PROTOCOL_VERSION` is in that file, so a mismatch only happens when the board
  has old code on it – and HELLO reports exactly that
- the simulated board (section 6) runs the board's real parsing code, and the
  pytest tests cover it

## 6. The simulated board

`sim` is the placeholder that lets the backend and frontend be built without
hardware. It is a transport, not a fake link: the full link (threads, state
machine, protocol, ACKs, stats) runs exactly as with a real port, and only the
bytes go to an object in memory instead of a USB cable.

The fake board:

- powers on when the port is opened, like a real board reset by opening the
  port: it prints the ESP32's boot messages as plain text (so the `RawText`
  path is used every time), then sends HELLO without being asked. Until then
  (`boot_ms`) it ignores everything it receives, like a real board whose
  `main.py` isn't running yet
- answers PING with HELLO: protocol version from `protocol.py`, firmware
  `0.0.0`, 10 LEDs, `GRB`. The link marks it as simulated
  (`DeviceInfo.simulated = True`), since HELLO's firmware field is only three
  numbers and can't say so itself
- parses frames with `protocol.py`, keeps the last picture (strip and matrix,
  for tests), and answers with ACK after a short delay (default 4 ms, like the
  real one)
- like `main.py`: a frame with the wrong LED count or an unknown message type
  is answered with a LOG; after a REPL message it stops speaking the protocol
  and shows MicroPython's banner and `>>>` prompt; without a frame for 3 s it
  counts as idle
- is set up in the URL, e.g. `sim?latency_ms=8&drop=0.02&seed=1`:

| Option | Default | |
|---|---|---|
| `latency_ms` | 4 | time until an answer arrives |
| `boot_ms` | 20 | time from power-on to the first output |
| `drop` | 0 | share of frames that get lost (no ACK, not shown) |
| `garbage` | 0 | share of answers with random bytes before them |
| `reboot_every` | 0 | seconds between reboots, 0 = never |
| `unplug_every` | 0 | seconds between unplugs, 0 = never; the port then fails like a pulled cable |
| `unplug_for` | 1 | seconds an unplug lasts; opening fails until then |
| `idle_after_ms` | 3000 | no frame for this long = idle |
| `led_count` | 10 | LEDs on the strip |
| `color_order` | `GRB` | the strip's colour order |
| `protocol` | current | protocol version in HELLO, to test INCOMPATIBLE |
| `seed` | random | makes `drop` and `garbage` repeatable |

Faults are off by default, so `sim` behaves like a healthy board in
development; the tests switch them on. An unknown option is an error, so a
typo doesn't silently test the wrong thing.

The code is in `hcl/transport/sim.py`: `FakeBoard` is the board,
`SimTransport` the port to it, with `unplug()` / `replug()` for pulling the
cable by hand. The HCL's own tests look at the board directly
(`transport.board.picture`, `.strip_rgb()`, `.idle`, `.boots`); tests above
the HCL use `hcl.testing` (section 3.6).

## 7. Board side (`src/hcl/esp/`)

### 7.1 Files

| File | |
|---|---|
| `boot.py` | empty apart from a comment; MicroPython runs it first |
| `main.py` | the loop below |
| `config.py` | pins, LED count, colour order, idle timeout |
| `max7219.py` | 8x8 driver: init, write 8 rows, brightness |
| `protocol.py` | copied from `hcl/protocol.py` on upload |

```python
# config.py
FIRMWARE = (1, 0, 0)
STRIP_PIN = 13
LED_COUNT = 10
COLOR_ORDER = "GRB"     # check with ./dod hcl pattern
SPI_ID = 2              # hardware SPI: CLK 18, DIN (MOSI) 23
MATRIX_CS = 5
SPI_BAUD = 1_000_000    # lower this first if the 8x8 glitches
IDLE_AFTER_MS = 3000
```

### 7.2 `main.py`

1. **Escape hatch:** for the first second, check the BOOT button (GPIO0). If it
   is held, return – the board stays in the REPL (see section 9).
2. `micropython.kbd_intr(-1)`, set up the strip and the matrix, send HELLO.
3. Loop:
   - poll `sys.stdin` (`select.poll`, ~5 ms timeout) and feed available bytes
     to the parser. Once a header is in, the rest of the frame is read in one
     `read(n)` **(verify that it doesn't stall)**.
   - **FRAME:** copy the strip bytes into the NeoPixel buffer (`np.buf[:] =
     strip`), `np.write()`, write the 8 rows and the brightness to the
     MAX7219, send ACK with the frame's seq
   - **PING:** send HELLO
   - **REPL:** send a LOG ("entering repl"), `kbd_intr(3)`, return
   - no FRAME for `IDLE_AFTER_MS`: own idle animation – slow breathing on the
     strip, a "waiting" animation on the 8x8 – until the next FRAME
   - every 5 s: re-send the MAX7219's setup registers, so a replugged or
     glitched matrix recovers by itself
4. Any exception inside the loop is sent as a LOG (error) and the loop goes on.
   If something escapes anyway, MicroPython prints the traceback on the port,
   and the host shows it as `RawText`.

## 8. Windows bridge (`src/hcl/bridge/serial-bridge.ps1`)

On the notebook the backend runs in Docker Desktop, which cannot pass a COM
port into a container (tech-spec 6.2). The bridge is a PowerShell script
started by `start.ps1`, using only what Windows has built in:

```
serial-bridge.ps1 -Port COM3 -TcpPort 7777
```

- opens the COM port with `System.IO.Ports.SerialPort`, 115200, DTR and RTS off
- listens on `127.0.0.1:7777` for one client at a time, copies bytes both
  ways, unchanged
- when the client (the container) disconnects, the COM port **stays open** and
  the next client is accepted – a backend restart doesn't reset the board
- when the board is unplugged, the client is disconnected and the script waits
  for the port to come back

For the HCL this is just the URL `socket://host.docker.internal:7777` –
pyserial handles it like a port, and none of the code above changes.
**(verify)**: throughput and latency, and that the container reaches the
host's `127.0.0.1`.

## 9. Tools

Run inside the container through the dev wrapper:

| Command | Does |
|---|---|
| `./dod hcl monitor` | connects, prints a status line every second and every event – the first thing to run when something is wrong. Only watches; `--send` adds a dim breathing test frame at 30 fps, so fps and round-trip times mean something; `--seconds N` stops by itself |
| `./dod hcl pattern` | wiring test, printing what should be visible at each step: the whole strip red, green, blue (shows the colour order), one white LED walking along the strip, each 8x8 row and column, a brightness ramp, then everything off. `--speed 2` runs it twice as fast |
| `./dod hcl bench` | sends frames as fast as the board ACKs them for 20 s (`--seconds`), reports fps, round trip min / avg / max, kB/s, timeouts and reconnects, then **PASS** (≥ 45 fps, no timeouts, no reconnects) or **FAIL** with the reason |
| `./dod hcl repl` | waits until `main.py` answers a PING (opening the port may have reset the board), sends the REPL message, waits for the confirmation; then `mpremote` can take over |
| `./dod esp upload` | `hcl repl`, then copies `src/hcl/esp/` and `protocol.py` to the board and resets it |

All of them take `--url` (default `$DOD_SERIAL`, else `sim`) and work with
the simulated board too. Exit codes, for scripts: 0 fine, 1 failed (no
board, bench FAIL), 2 bad option or URL – for `repl` also "main.py didn't
answer", which is fine if the board is already at the `>>>` prompt –, 130
stopped with Ctrl-C.

If the board doesn't react to the REPL frame: press EN (reset), release it,
then hold BOOT for 1 s (section 7.2, step 1). Holding BOOT *while* pressing EN
starts the bootloader instead, which is only for flashing MicroPython.

The backend must not run at the same time as the tools – only one program can
have the port open.

## 10. How the backend uses it

- On startup: `open_link(DOD_SERIAL, ...)` and `start()`.
- Render loop, every tick: power limit, flash limit, then `submit(frame)`.
- One task reads `link.events()` and forwards them to the log generator
  (connects, reboots, board logs become log lines) and to the state behind
  the main screen's status badge.
- `/api/status` includes `link.status`.
- The previews on the pages come from the backend's own frames, not from the
  HCL – they look the same whether a board is connected or not.
- The backend imports only from `hcl` itself, never from `hcl.transport` or
  `hcl.protocol`; its tests may also use `hcl.testing` (section 3.6). A test
  checks the backend's imports.

## 11. Tests

All in `src/hcl/tests`, run by `./dod test`, none need hardware:

- **protocol:** encode → parse round trip for every type; wrong checksum;
  garbage before, between and inside frames; a frame split into single bytes;
  oversized length; text garbage comes out as lines
- **link with `sim`:** connects and gets HELLO; reconnects after an unplug;
  a reboot gives `Connected(rebooted=True)`; ACK timeouts lead to
  DISCONNECTED; a different protocol version gives INCOMPATIBLE
- **newest frame wins:** submitting 100 frames while the board is slow sends
  only the newest ones, nothing piles up, `frames_replaced` counts the rest
- **colour order:** RGB in, the board's order on the wire
- **keepalive:** with nothing submitted, the last frame is repeated every
  `keepalive_ms`, and the fake board never goes idle
- **frame checks:** `submit()` rejects wrong shapes
- **`hcl.testing`:** frames reach the board; `unplug()` gives `Disconnected` and
  keeps the board gone until `replug()`; bad timings and URLs are refused; the
  transports stay out of `hcl`'s exports

On real hardware later: `./dod hcl pattern` (wiring, colour order) and
`./dod hcl bench` (speed) are the checks for the board side (tech-spec plan, phase 3).

## 12. Build order

1. **Now, no hardware:** public API, `protocol.py`, the link, the simulated
   board, the serial transport (a thin pyserial wrapper – it can be written
   now and tested later), the tools, all tests. The backend is built on top of
   this with `DOD_SERIAL=sim`.
2. **Board on the desk (WSL):** `src/hcl/esp/`, then `pattern` and `bench`
   against `/dev/ttyUSB0`. This answers the **(verify)** items in sections
   4.2, 5.4 and 7.2.
3. **Teacher's notebook:** `serial-bridge.ps1`, then `bench` through
   `socket://host.docker.internal:7777`. Answers section 8's **(verify)**.

Step 3 is the riskiest part of the whole project (tech-spec 6.2), so it
should happen as soon as the notebook is available, not after everything else.
